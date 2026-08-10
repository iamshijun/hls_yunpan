"""百度网盘服务 - 负责与百度网盘API交互"""
import asyncio
import os
import httpx
from typing import Optional, List, Dict, AsyncIterator, Callable, Awaitable
import logging
import traceback


logger = logging.getLogger(__name__)

# API 元数据请求超时
_API_TIMEOUT = 30.0
# 文件下载流式超时 — 分片文件可能上百 MB, 留足时间
_DOWNLOAD_STREAM_TIMEOUT = 300.0
# 文件上传超时（单文件可能上百 MB）
_UPLOAD_TIMEOUT = 600.0
# 上传接口
UPLOAD_URL = "https://d.pcs.baidu.com/rest/2.0/pcs/file"


class BaiduYunService:
    """百度网盘服务类"""

    def __init__(self, access_token: Optional[str] = None):
        self.access_token = access_token
        self.client = httpx.AsyncClient(
            timeout=_API_TIMEOUT,
            follow_redirects=True,
        )
        self.batch_size = 1000  # 单次获取最大数量

    async def get_file_list_all(self, path: str = "/") -> List[Dict]:
        """
        获取指定路径下的所有文件列表（支持分批获取）

        Args:
            path: 网盘路径，默认为根目录

        Returns:
            完整的文件列表
        """
        all_files = []
        start = 0

        while True:
            files = await self.get_file_list(path, start, self.batch_size)

            if not files:
                break

            all_files.extend(files)

            # 如果返回数量少于批次大小，说明已获取完所有文件
            if len(files) < self.batch_size:
                break

            start += self.batch_size
            logger.info(f"已获取 {len(all_files)} 个文件，继续获取...")

        logger.info(f"目录 [{path}] 共有 {len(all_files)} 个文件")
        return all_files

    async def get_file_list(self, path: str = "/", start: int = 0, limit: int = 1000) -> List[Dict]:
        """
        获取指定路径下的文件列表

        Args:
            path: 网盘路径，默认为根目录
            start: 起始位置
            limit: 返回数量限制，最大1000

        Returns:
            文件列表
        """
        try:
            # 百度网盘API获取文件列表
            url = "https://pan.baidu.com/rest/2.0/xpan/file"
            params = {
                "method": "list",
                "dir": path,
                "order": "name",
                "start": start,
                "limit": limit,
                "access_token": self.access_token
            }
            headers = self._get_headers()

            response = await self.client.get(url, params=params, headers=headers)
            response.raise_for_status()

            data = response.json()

            if data.get("errno") != 0:
                logger.error(f"获取文件列表失败: {data.get('errmsg', 'Unknown error')}")
                return []

            return data.get("list", [])
        except Exception as e:
            logger.error(f"获取文件列表失败: {e}")
            traceback.print_exc()
            raise

    async def search_file(self, key: str, dir_path: str = "/") -> List[Dict]:
        """在指定目录下搜索文件（百度网盘 search API）。

        Args:
            key: 搜索关键词（通常是文件名，如 "metadata.txt"）
            dir_path: 搜索的起始目录

        Returns:
            命中文件列表（与 list 接口相同的 list 元素结构），失败返回空列表。
        """
        try:
            url = "https://pan.baidu.com/rest/2.0/xpan/file"
            params = {
                "method": "search",
                "access_token": self.access_token,
                "key": key,
                "dir": dir_path,
                "recursion": 1,  # 搜子目录，避免用户路径带子目录
                "page": 1,
                "size": 50,
            }
            headers = self._get_headers()
            response = await self.client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            if data.get("errno") != 0:
                logger.warning(
                    f"search failed: {data.get('errmsg')} (errno={data.get('errno')})"
                )
                return []
            return data.get("list", [])
        except Exception as e:
            logger.error(f"搜索文件失败 [{dir_path} / {key}]: {e}")
            return []

    async def download_file(self, file_path: str, fsid: Optional[int] = None) -> bytes:
        """
        下载文件

        Args:
            file_path: 网盘文件路径
            fsid: 文件系统ID（可选，如果提供则使用fsid获取下载链接）

        Returns:
            文件内容
        """
        try:
            # 首先获取文件的下载链接
            download_url = await self._get_download_url(file_path, fsid)
            logger.info(f'download_url of {file_path} : {download_url} ')
            # 下载文件
            response = await self.client.get(download_url, follow_redirects=True,
                params= {
                    "access_token" : self.access_token
                },
                headers= {
                    "User-Agent" : "pan.baidu.com"
                })
            # logger.info(f"下载响应 [{file_path}] status={response.status_code} final_url={response.url}")
            # logger.info(f"重定向链 [{file_path}]: {[(h.status_code, str(h.url)) for h in response.history]}")
            response.raise_for_status()

            return response.content
        except Exception as e:
            traceback.print_exc()
            logger.error(f"下载文件失败 [{file_path}]: {e}")
            raise

    async def stream_download(
        self,
        file_path: str,
        fsid: Optional[int] = None,
    ) -> AsyncIterator[bytes]:
        """流式下载文件, 边下载边产出字节块.

        用于 FastAPI StreamingResponse, 避免等待整个文件下载完毕才向
        客户端发送第一个字节, 从而防止浏览器 / hls.js 超时断开连接。

        Yields:
            bytes chunks (默认 64 KB).
        """
        download_url = await self._get_download_url(file_path, fsid)

        async with self.client.stream(
            "GET",
            download_url,
            params={"access_token": self.access_token},
            headers={"User-Agent": "pan.baidu.com"},
            follow_redirects=True,
            timeout=httpx.Timeout(
                _DOWNLOAD_STREAM_TIMEOUT,
                connect=_API_TIMEOUT,
            ),
        ) as resp:
            # logger.info(f"流式下载响应 [{file_path}] status={resp.status_code} final_url={resp.url}")
            # logger.info(f"重定向链 [{file_path}]: {[(h.status_code, str(h.url)) for h in resp.history]}")
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes(chunk_size=65536):
                yield chunk

    async def _get_download_url(self, file_path: str, fsid: Optional[int] = None) -> str:
        """
        获取文件下载链接

        Args:
            file_path: 网盘文件路径
            fsid: 文件系统ID（可选）

        Returns:
            下载链接
        """
        url = "https://pan.baidu.com/rest/2.0/xpan/multimedia"
        params = {
            "method": "filemetas",
            "access_token": self.access_token,
            "dlink" : 1
        }

        # 优先使用fsid
        if fsid is not None:
            params["fsids"] = f"[{fsid}]"
        elif file_path:
            # 如果没有fsid，使用path参数（但这个API可能不支持path参数）
            # 需要先通过list获取fsid
            logger.warning(f"未提供fsid，尝试使用path获取下载链接")
            # 这里可能需要先调用list获取fsid
            raise ValueError("获取下载链接需要提供fsid")

        headers = self._get_headers()
        
        response = await self.client.get(url, params=params, headers=headers)
        response.raise_for_status()

        data = response.json()
        if data.get("errno") != 0:
            logger.error(f"获取下载链接失败: {data.get('errmsg', 'Unknown error')}")
            raise Exception(f"获取下载链接失败: {data}")

        # 返回第一个文件的dlink
        if "list" in data and len(data["list"]) > 0:
            return data["list"][0].get("dlink")

        return None

    def _get_headers(self) -> dict:
        """构建请求头"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }
        return headers

    # ---- 上传 ----

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