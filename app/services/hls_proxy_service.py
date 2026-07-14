"""HLS代理服务 - 负责HLS请求的代理和转换"""
from fastapi import Response
from fastapi.responses import StreamingResponse
import asyncio
import os
from typing import Optional, AsyncIterator
import logging
from .baiduyun_service import BaiduYunService
from .cache_service import CacheService
from ..utils.m3u8_parser import M3U8Parser

logger = logging.getLogger(__name__)

class HLSProxyService:
    """HLS代理服务类"""

    def __init__(
        self,
        yun_service: BaiduYunService,
        cache_service: CacheService,
        hls_root_path: str = "/hls",
        cache_segments: bool = False
    ):
        self.yun_service = yun_service
        self.cache_service = cache_service
        self.hls_root_path = hls_root_path
        self.cache_segments = cache_segments
        self.parser = M3U8Parser()
        self.dir_locks = {}  # 目录加载锁: {dir_path: Lock}

    def _get_dir_lock(self, dir_path: str) -> asyncio.Lock:
        """获取目录锁"""
        if dir_path not in self.dir_locks:
            self.dir_locks[dir_path] = asyncio.Lock()
        return self.dir_locks[dir_path]

    async def _load_directory_fsids(self, dir_path: str) -> None:
        """
        加载目录下所有文件的fsid并缓存

        Args:
            dir_path: 网盘目录路径
        """
        lock = self._get_dir_lock(dir_path)

        async with lock:
            logger.info(f"开始加载目录 [{dir_path}] 的文件列表和fsid...")

            try:
                # 获取目录下所有文件
                files = await self.yun_service.get_file_list_all(dir_path)

                # 构建文件路径到fsid的映射
                fsid_map = {}
                for file_info in files:
                    file_path = file_info.get("path")
                    fsid = file_info.get("fs_id")
                    if file_path and fsid:
                        fsid_map[file_path] = fsid

                # 批量缓存fsid映射
                await self.cache_service.set_fsids(dir_path, fsid_map)

                logger.info(f"目录 [{dir_path}] 加载完成，共 {len(fsid_map)} 个文件")
            except Exception as e:
                logger.error(f"加载目录 [{dir_path}] 失败: {e}")
                raise

    async def handle_m3u8_request(self, request_path: str) -> Response:
        """
        处理m3u8文件请求

        Args:
            request_path: 请求路径

        Returns:
            FastAPI Response
        """
        try:
            # 将请求路径转换为网盘路径
            yun_path = self._convert_to_yun_path(request_path)
            dir_path = os.path.dirname(yun_path) or "/"

            logger.info(f"处理m3u8请求: {request_path} -> {yun_path}")

            # 尝试从缓存获取
            content = await self.cache_service.get(yun_path)
            if content:
                # 需要重写m3u8中的URL
                rewritten = await self._rewrite_m3u8_urls(content, request_path)
                return Response(
                    content=rewritten,
                    media_type="application/vnd.apple.mpegurl",
                    headers={
                        "Cache-Control": "public, max-age=3600",
                        "Access-Control-Allow-Origin": "*"
                    }
                )

            # 首次访问：加载目录下的所有文件fsid
            await self._load_directory_fsids(dir_path)

            # 从缓存获取fsid
            fsid = await self.cache_service.get_fsid(yun_path)
            if fsid is None:
                logger.error(f"未找到文件的fsid: {yun_path}")
                return Response(
                    status_code=404,
                    content=f"File not found: {yun_path}"
                )

            # 从网盘下载（使用fsid）
            content = await self.yun_service.download_file(yun_path, fsid=fsid)

            # 缓存文件
            await self.cache_service.set(yun_path, content)

            # 重写m3u8中的URL
            rewritten = await self._rewrite_m3u8_urls(content, request_path)

            return Response(
                content=rewritten,
                media_type="application/vnd.apple.mpegurl",
                headers={
                    "Cache-Control": "public, max-age=3600",
                    "Access-Control-Allow-Origin": "*"
                }
            )

        except Exception as e:
            logger.error(f"处理m3u8请求失败: {e}")
            import traceback
            traceback.print_exc()
            return Response(
                status_code=500,
                content=f"Error: {str(e)}"
            )

    async def handle_chunk_request(self, request_path: str) -> Response:
        """
        处理分片文件请求

        Args:
            request_path: 请求路径

        Returns:
            FastAPI Response
        """
        try:
            # 将请求路径转换为网盘路径
            yun_path = self._convert_to_yun_path(request_path)
            dir_path = os.path.dirname(yun_path) or "/"

            logger.info(f"处理分片请求: {request_path} -> {yun_path}")

            # 尝试从缓存获取
            content = await self.cache_service.get(yun_path)
            if content:
                # 启用缓存时使用缓存的文件内容和长缓存时间
                return Response(
                    content=content,
                    media_type="video/mp2t",
                    headers={
                        "Cache-Control": "public, max-age=86400",
                        "Access-Control-Allow-Origin": "*"
                    }
                )

            # 从缓存获取fsid
            fsid = await self.cache_service.get_fsid(yun_path)

            # 如果没有fsid，尝试加载目录
            if fsid is None:
                logger.warning(f"分片文件fsid未缓存，尝试加载目录: {dir_path}")
                await self._load_directory_fsids(dir_path)
                fsid = await self.cache_service.get_fsid(yun_path)

            if fsid is None:
                logger.error(f"未找到分片文件的fsid: {yun_path}")
                return Response(
                    status_code=404,
                    content=f"File not found: {yun_path}"
                )

            # 流式下载 — 边下边发给客户端，避免等待全部下载导致超时
            if self.cache_segments:
                # 启用缓存时使用长缓存时间
                cache_header = "public, max-age=86400"
            else:
                # 禁用缓存时使用no-cache
                cache_header = "no-cache"
                logger.info(f"分片缓存已禁用，流式下载并跳过缓存: {yun_path}")

            return StreamingResponse(
                self._stream_and_cache_chunk(yun_path, fsid),
                media_type="video/mp2t",
                headers={
                    "Cache-Control": cache_header,
                    "Access-Control-Allow-Origin": "*",
                },
            )

        except Exception as e:
            logger.error(f"处理分片请求失败: {e}")
            import traceback
            traceback.print_exc()
            return Response(
                status_code=500,
                content=f"Error: {str(e)}"
            )

    async def _stream_and_cache_chunk(
        self, yun_path: str, fsid: int,
    ) -> AsyncIterator[bytes]:
        """流式下载分片文件并产出字节块，结束后自动写入了本地缓存."""
        chunks: list[bytes] = []
        async for chunk in self.yun_service.stream_download(
            yun_path, fsid=fsid,
        ):
            chunks.append(chunk)
            yield chunk

        # 全部发送完成后再写入缓存（低优先级，不阻塞客户端）
        if self.cache_segments:
            full = b"".join(chunks)
            await self.cache_service.set(yun_path, full)
        else:
            logger.info(f"分片缓存已禁用，跳过缓存: {yun_path}")

    def _convert_to_yun_path(self, request_path: str) -> str:
        """
        将请求路径转换为网盘路径

        Args:
            request_path: HTTP请求路径

        Returns:
            网盘文件路径
        """
        # 移除URL前缀
        if request_path.startswith(self.hls_root_path):
            request_path = request_path[len(self.hls_root_path):]

        # 转换为网盘路径
        return f"/apps/movies{request_path}"

    async def _rewrite_m3u8_urls(self, content: bytes, base_path: str) -> bytes:
        """
        重写m3u8文件中的URL

        Args:
            content: m3u8文件内容
            base_path: 基础路径

        Returns:
            重写后的内容
        """
        try:
            m3u8_text = content.decode('utf-8')
            lines = m3u8_text.split('\n')
            result = []

            base_dir = '/'.join(base_path.split('/')[:-1])

            for line in lines:
                # 检查是否是分片URI
                if line and not line.startswith('#'):
                    # 重写分片URL
                    if not line.startswith('http'):
                        # 相对路径
                        chunk_path = f"{base_dir}/{line}".replace('//', '/')
                    else:
                        # 绝对路径
                        chunk_path = line

                    result.append(chunk_path)
                else:
                    result.append(line)

            return '\n'.join(result).encode('utf-8')
        except Exception as e:
            logger.error(f"重写m3u8 URL失败: {e}")
            return content