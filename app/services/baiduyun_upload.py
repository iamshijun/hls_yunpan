"""百度网盘上传 — 独立于读取侧（BaiduYunService）的上传客户端。

上传只被 CLI（app.upload）使用，运行时服务不需要它，因此从 baiduyun_service.py
拆出，避免读取路径背负上传相关的依赖与常量。
"""
import asyncio
import os
import logging
from typing import Awaitable, Callable, Dict, Optional

import httpx


logger = logging.getLogger(__name__)

# API 元数据请求超时
_API_TIMEOUT = 30.0
# 文件上传超时（单文件可能上百 MB）
_UPLOAD_TIMEOUT = 600.0
# 上传接口
UPLOAD_URL = "https://d.pcs.baidu.com/rest/2.0/pcs/file"


class BaiduYunUploader:
    """百度网盘上传客户端（带指数退避重试）。"""

    def __init__(self, access_token: Optional[str] = None):
        self.access_token = access_token
        self.client = httpx.AsyncClient(
            timeout=_API_TIMEOUT,
            follow_redirects=True,
        )

    async def upload_file(
        self,
        local_path: str,
        remote_path: str,
        ondup: str = "overwrite",
        max_retries: int = 5,
    ) -> Dict:
        """上传本地文件到网盘（带指数退避重试）。

        Args:
            local_path: 本地文件路径
            remote_path: 网盘目标路径
            ondup: 同名处理 (fail / overwrite / newcopy)
            max_retries: 最大重试次数，0 表示不重试
        """
        filename = os.path.basename(local_path)

        async def _attempt() -> Dict:
            with open(local_path, 'rb') as fh:
                return await self._upload_request(fh, filename, remote_path, ondup)

        return await self._upload_with_retry(_attempt, name=filename, max_retries=max_retries)

    async def upload_bytes(
        self,
        data: bytes,
        filename: str,
        remote_path: str,
        ondup: str = "overwrite",
        max_retries: int = 5,
    ) -> Dict:
        """上传内存中的字节流到网盘（带重试）。"""
        async def _attempt() -> Dict:
            return await self._upload_request(data, filename, remote_path, ondup)

        return await self._upload_with_retry(_attempt, name=filename, max_retries=max_retries)

    async def _upload_request(self, file_obj, filename: str, remote_path: str, ondup: str) -> Dict:
        """执行一次上传请求并解码 errno，失败抛异常。"""
        response = await self.client.post(
            UPLOAD_URL,
            params={
                "method": "upload",
                "access_token": self.access_token,
                "path": remote_path,
                "ondup": ondup,
                "rtype": 3,
            },
            files={"file": (filename, file_obj, "application/octet-stream")},
            timeout=httpx.Timeout(_UPLOAD_TIMEOUT, connect=_API_TIMEOUT),
        )
        if response.status_code != 200:
            raise RuntimeError(f"HTTP error {response.status_code}: {response.text}")

        result: Dict = response.json()
        errno = result.get("errno")
        if errno is not None and errno != 0:
            raise RuntimeError(f"API errno={errno}: {result.get('errmsg', 'unknown error')}")
        return result

    async def _upload_with_retry(self, attempt: Callable[[], Awaitable[Dict]], name: str, max_retries: int) -> Dict:
        """带指数退避重试执行上传。

        Retry delays: 1 s, 2 s, 4 s, 8 s, ...
        """
        last_error = None
        for i in range(max_retries + 1):
            if i > 0:
                delay = 2 ** (i - 1)
                logger.info(f"[retry {i}/{max_retries}] {name} (wait {delay}s)")
                await asyncio.sleep(delay)
            try:
                return await attempt()
            except (httpx.HTTPStatusError, httpx.RequestError, RuntimeError, OSError) as e:
                last_error = e
        raise RuntimeError(f"Failed after {max_retries} retries: {last_error}") from last_error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def close(self):
        """关闭客户端"""
        await self.client.aclose()
