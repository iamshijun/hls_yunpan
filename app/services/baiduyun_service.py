"""百度网盘服务 - 负责与百度网盘API交互"""
import httpx
from typing import Optional, List, Dict, AsyncIterator
import logging
import traceback


logger = logging.getLogger(__name__)

# API 元数据请求超时
_API_TIMEOUT = 30.0
# 文件下载流式超时 — 分片文件可能上百 MB, 留足时间
_DOWNLOAD_STREAM_TIMEOUT = 300.0


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

            # 下载文件
            response = await self.client.get(download_url, follow_redirects=True,
                params= {
                    "access_token" : self.access_token
                },
                headers= {
                    "User-Agent" : "pan.baidu.com"
                })
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

    async def get_download_urls_by_fsids(self, fsids: List[int]) -> Dict[int, str]:
        """
        批量通过fsid获取下载链接

        Args:
            fsids: fsid列表

        Returns:
            {fsid: dlink} 映射
        """
        if not fsids:
            return {}

        url = "https://pan.baidu.com/rest/2.0/xpan/multimedia"
        params = {
            "method": "filemetas",
            "fsids": str(fsids).replace(" ", ""),
            "access_token": self.access_token
        }
        headers = self._get_headers()

        response = await self.client.get(url, params=params, headers=headers)
        response.raise_for_status()

        data = response.json()

        if data.get("errno") != 0:
            logger.error(f"批量获取下载链接失败: {data.get('errmsg', 'Unknown error')}")
            return {}

        # 构建 {fsid: dlink} 映射
        result = {}
        for item in data.get("list", []):
            fsid = item.get("fsid")
            dlink = item.get("dlink")
            if fsid and dlink:
                result[fsid] = dlink

        return result

    async def get_file_info(self, file_path: str) -> dict:
        """
        获取文件信息

        Args:
            file_path: 网盘文件路径

        Returns:
            文件信息
        """
        try:
            url = "https://pan.baidu.com/rest/2.0/xpan/file"
            params = {
                "method": "meta",
                "path": file_path,
                "access_token": self.access_token
            }
            headers = self._get_headers()

            response = await self.client.get(url, params=params, headers=headers)
            response.raise_for_status()

            return response.json()
        except Exception as e:
            logger.error(f"获取文件信息失败 [{file_path}]: {e}")
            raise

    def _get_headers(self) -> dict:
        """构建请求头"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }
        return headers

    async def close(self):
        """关闭客户端"""
        await self.client.aclose()