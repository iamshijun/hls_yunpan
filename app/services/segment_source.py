"""HLS 内容源抽象

将"从哪读取 HLS 内容"抽成 SegmentSource 接口，提供两个适配器：
- LocalSource: 本地磁盘（异步流式读取，不再整文件读入内存）
- YunSource:   百度网盘（走 fsid + 缓存 + 下载/流式）

接口返回一个可流式读取的内容体（async iterator of bytes）或 None：
- None 表示本源无法提供该文件（映射 404）
- 返回体始终可迭代，是否缓冲由调用方（HLSProxyService）决定 ——
  需要重写（m3u8）时缓冲成 bytes，否则直接 StreamingResponse。

组合方式决定请求由谁服务：本地模式时仅使用 LocalSource（缺失即 404），
否则使用 YunSource。流水线（HLSProxyService）按顺序尝试各源，命中即响应。
"""
import asyncio
import logging
import os
from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, Optional

import aiofiles

from .baiduyun_service import BaiduYunService, YunNotFoundError
from .cache_service import CacheService

logger = logging.getLogger(__name__)

# 路由前缀固定为 /hls（见 app/routes/hls.py => APIRouter(prefix="/hls", ...），请求路径始终以此开头，
# 各源剥掉该前缀后映射到自己的内容根（本地磁盘 / 网盘）。
HLS_URL_PREFIX = "/hls"

# 一个可流式读取的内容体：async iterator，逐块产出字节。
BytesBody = AsyncIterator[bytes]


class SegmentSource(ABC):
    """HLS 内容源。resolve 返回 None 表示本源无法提供该文件。"""

    @abstractmethod
    async def resolve(self, request_path: str) -> Optional[BytesBody]:
        """解析请求路径为可流式读取的内容体。

        Args:
            request_path: HTTP 请求路径（含 /hls 前缀）

        Returns:
            内容体（async iterator of bytes），或 None（本源无法提供该文件）。
        """
        ...


class LocalSource(SegmentSource):
    """本地磁盘内容源（异步流式读取，内存占用恒定）。"""

    def __init__(self, local_path: str):
        self.local_path = local_path

    async def resolve(self, request_path: str) -> Optional[BytesBody]:
        file_path = self._get_local_file_path(request_path)
        if not os.path.exists(file_path):
            return None
        return self._stream_file(file_path)

    def _get_local_file_path(self, request_path: str) -> str:
        """将请求路径映射到本地文件路径。(截掉hls route前缀)"""
        if request_path.startswith(HLS_URL_PREFIX):
            request_path = request_path[len(HLS_URL_PREFIX):]
        return os.path.join(self.local_path, request_path.lstrip('/'))

    def _stream_file(self, file_path: str) -> BytesBody:
        async def gen():
            async with aiofiles.open(file_path, "rb") as f:
                while True:
                    chunk = await f.read(65536)
                    if not chunk:
                        break
                    yield chunk
        return gen()


class YunSource(SegmentSource):
    """百度网盘内容源"""

    def __init__(
        self,
        yun_service: BaiduYunService,
        cache_service: CacheService,
        yun_path_prefix: str = "/apps/movies",
        cache_segments: bool = False,
    ):
        self.yun_service = yun_service
        self.cache_service = cache_service
        self.yun_path_prefix = yun_path_prefix
        self.cache_segments = cache_segments
        self.dir_locks: Dict[str, asyncio.Lock] = {}

    async def resolve(self, request_path: str) -> Optional[BytesBody]:
        yun_path = self._convert_to_yun_path(request_path)
        dir_path = os.path.dirname(yun_path) or "/"

        # 内容缓存
        content = await self.cache_service.get(yun_path)
        if content is not None:
            return self._bytes_body(content)

        # fsid（缺失时加载目录后重试）；确定不存在 → None(404)
        fsid = await self._resolve_fsid(yun_path, dir_path)
        if fsid is None:
            return None

        return self._stream_and_cache_chunk(yun_path, fsid)

    def _convert_to_yun_path(self, request_path: str) -> str:
        """将请求路径转换为网盘路径。(截掉hls route前缀,后面的即为云盘的路径)"""
        if request_path.startswith(HLS_URL_PREFIX):
            request_path = request_path[len(HLS_URL_PREFIX):]
        return f"{self.yun_path_prefix}{request_path}"

    def _bytes_body(self, content: bytes) -> BytesBody:
        async def gen():
            if content:
                yield content
        return gen()

    def _get_dir_lock(self, dir_path: str) -> asyncio.Lock:
        if dir_path not in self.dir_locks:
            self.dir_locks[dir_path] = asyncio.Lock()
        return self.dir_locks[dir_path]

    async def _load_directory_fsids(self, dir_path: str) -> None:
        """加载目录下所有文件的fsid并缓存。"""
        lock = self._get_dir_lock(dir_path)

        async with lock:
            logger.info(f"开始加载目录 [{dir_path}] 的文件列表和fsid...")
            try:
                files = await self.yun_service.get_file_list_all(dir_path)

                fsid_map = {}
                for file_info in files:
                    file_path = file_info.get("path")
                    fsid = file_info.get("fs_id")
                    if file_path and fsid:
                        fsid_map[file_path] = fsid

                await self.cache_service.set_fsids(dir_path, fsid_map)
                logger.info(f"目录 [{dir_path}] 加载完成，共 {len(fsid_map)} 个文件")
            except Exception as e:
                logger.error(f"加载目录 [{dir_path}] 失败: {e}")
                raise

    async def _resolve_fsid(self, yun_path: str, dir_path: str) -> Optional[int]:
        """解析文件的 fsid；未命中时加载目录 fsid 后重试。

        目录/文件确定不存在（YunNotFoundError）→ 返回 None（调用方映射 404）。
        其他 API 错误（认证/限流等）向上抛，由代理层映射 500。
        """
        try:
            fsid = await self.cache_service.get_fsid(yun_path)
            if fsid is None:
                logger.warning(f"文件fsid未缓存，尝试加载目录: {dir_path}")
                await self._load_directory_fsids(dir_path)
                fsid = await self.cache_service.get_fsid(yun_path)
            return fsid
        except YunNotFoundError:
            return None

    async def _stream_and_cache_chunk(self, yun_path: str, fsid: int) -> BytesBody:
        """流式下载分片文件并产出字节块，结束后自动写入了本地缓存。"""
        chunks: list[bytes] = []
        async for chunk in self.yun_service.stream_download(yun_path, fsid=fsid):
            chunks.append(chunk)
            yield chunk

        if self.cache_segments:
            full = b"".join(chunks)
            await self.cache_service.set(yun_path, full)
        else:
            logger.debug(f"分片缓存已禁用，跳过缓存: {yun_path}")
