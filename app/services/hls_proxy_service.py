"""HLS代理服务 - 负责HLS请求的代理和转换"""
from dataclasses import dataclass
from fastapi import Response
from fastapi.responses import StreamingResponse
import os
import logging
from .baiduyun_service import BaiduYunService
from .cache_service import CacheService
from .segment_source import SegmentSource, LocalSource, YunSource, BytesBody
from ..utils.m3u8_parser import M3U8Parser

logger = logging.getLogger(__name__)


class HLSProxyError(Exception):
    """HLS 代理内部错误，由 FastAPI 异常处理器转换为 HTTP 响应。"""


@dataclass(frozen=True)
class ServeOptions:
    """HLS 文件响应选项 - m3u8 与分片流程的差异点。

    rewrite=True 时（m3u8）需要整份内容做 URL 重写，故先缓冲成 bytes；
    否则直接 StreamingResponse 流式返回分片。
    """
    media_type: str
    cache_header: str
    rewrite: bool = False               # 是否需要重写 m3u8 中的 URL（隐式决定缓冲）


class HLSProxyService:
    """HLS代理服务类

    通过组合 SegmentSource（本地 / 网盘）决定请求由谁服务，自身只负责
    流水线编排与 HTTP 响应构建。
    """

    def __init__(
        self,
        yun_service: BaiduYunService,
        cache_service: CacheService,
        yun_path_prefix: str = "/apps/movies",
        cache_segments: bool = False,
        local_path: str = "./local_hls"
    ):
        self.cache_segments = cache_segments
        self.parser = M3U8Parser()

        # 组合内容源：本地模式权威（缺失即404），否则使用网盘
        self.local_mode = os.path.exists(local_path) and os.path.isdir(local_path)
        if self.local_mode:
            self.sources: list[SegmentSource] = [
                LocalSource(local_path=local_path)
            ]
            logger.info(f"本地模式已启用，仅使用本地目录: {local_path}")
        else:
            self.sources = [
                YunSource(
                    yun_service=yun_service,
                    cache_service=cache_service,
                    yun_path_prefix=yun_path_prefix,
                    cache_segments=cache_segments,
                )
            ]
            logger.info(f"本地目录{local_path}不存在或不可访问，将使用网盘模式")

    async def handle_m3u8_request(self, request_path: str) -> Response:
        """处理m3u8播放列表请求"""
        logger.info(f"处理m3u8请求: {request_path}")
        return await self._serve(
            request_path,
            ServeOptions(
                media_type="application/vnd.apple.mpegurl",
                cache_header="public, max-age=3600",
                rewrite=True,
            ),
        )

    async def handle_chunk_request(self, request_path: str) -> Response:
        """处理分片文件请求"""
        logger.info(f"处理分片请求: {request_path}")
        cache_header = "public, max-age=86400" if self.cache_segments else "no-cache"
        return await self._serve(
            request_path,
            ServeOptions(
                media_type="video/mp2t",
                cache_header=cache_header,
            ),
        )

    async def _serve(self, request_path: str, options: ServeOptions) -> Response:
        """流水线 - 依次尝试各内容源，命中后构建 HTTP 响应。"""
        try:
            for source in self.sources:
                body = await source.resolve(request_path)
                if body is not None:
                    return await self._build_response(body, options)

            logger.error(f"未找到文件: {request_path}")
            return Response(
                status_code=404,
                content=f"File not found: {request_path}"
            )

        except Exception as e:
            logger.error(f"处理HLS请求失败 [{request_path}]: {e}", exc_info=True)
            raise HLSProxyError(f"Error: {str(e)}") from e

    async def _build_response(
        self, body: BytesBody, options: ServeOptions
    ) -> Response:
        """将源解析结果转换为 HTTP 响应。

        需要重写（m3u8）时把内容体缓冲成 bytes 再重写；否则流式返回分片。
        """
        if options.rewrite:
            content = b"".join([chunk async for chunk in body])
            content = self.parser.rewrite(content)
            return self._ok_response(content, options)

        return StreamingResponse(
            body,
            media_type=options.media_type,
            headers=self._headers(options),
        )

    def _headers(self, options: ServeOptions) -> dict:
        """构建响应头"""
        return {
            "Cache-Control": options.cache_header,
            "Access-Control-Allow-Origin": "*",
        }

    def _ok_response(self, content: bytes, options: ServeOptions) -> Response:
        """构建成功响应"""
        return Response(
            content=content,
            media_type=options.media_type,
            headers=self._headers(options),
        )
