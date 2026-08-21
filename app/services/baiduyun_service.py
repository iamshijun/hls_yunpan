"""百度网盘服务 - 负责与百度网盘API交互（读取侧）

只保留运行时的读操作：列表 / 搜索 / 下载 / 流式下载 / 元数据。
上传逻辑已拆到 baiduyun_upload.py（BaiduYunUploader），仅供 CLI 使用。
"""
import httpx
import logging
import traceback
from typing import AsyncIterator, Dict, List, Optional


logger = logging.getLogger(__name__)

# API 元数据请求超时
_API_TIMEOUT = 30.0
# 文件下载流式超时 — 分片文件可能上百 MB, 留足时间
_DOWNLOAD_STREAM_TIMEOUT = 300.0


class YunAPIError(Exception):
    """BaiduYun API 错误（errno != 0）。errno 保留在异常上供调用方分类。"""

    def __init__(self, errno: int, message: str = ""):
        self.errno = errno
        self.message = message or f"BaiduYun API error (errno={errno})"
        super().__init__(self.message)


class YunNotFoundError(YunAPIError):
    """文件/目录确定不存在 —— 应映射为 404，而不是 500。"""


class YunAuthError(YunAPIError):
    """认证失败（access_token 无效/过期）—— 应映射为 500/502，而不是 404。"""


# errno 分类。百度网盘 xpan 常见返回码：-9 文件不存在、-12 目录不存在、-6 身份验证失败。
# 无法 100% 确定某些 errno 的语义，这里只收窄确定的一小撮；其余一律按通用 API 错误处理，
# 避免把认证/限流误判成「文件不存在」而返回 404。
NOT_FOUND_ERRNOS = {-9, -12}
AUTH_ERRNOS = {-6}


def _classify_errno(errno: int, message: str = "") -> YunAPIError:
    """按 errno 分派到具体异常类型；未归类的一律返回通用 YunAPIError。"""
    if errno in NOT_FOUND_ERRNOS:
        return YunNotFoundError(errno, message)
    if errno in AUTH_ERRNOS:
        return YunAuthError(errno, message)
    return YunAPIError(errno, message)


class BaiduYunService:
    """百度网盘服务类"""

    def __init__(self, access_token: Optional[str] = None):
        self.access_token = access_token
        self.client = httpx.AsyncClient(
            timeout=_API_TIMEOUT,
            follow_redirects=True,
        )
        self.batch_size = 1000  # 单次获取最大数量

    async def _get_json(self, url: str, params: Dict) -> Dict:
        """GET 请求并统一处理 errno；网络/HTTP 错误直接上抛。

        返回解码后的 JSON dict（errno 已确认为 0）。
        """
        headers = self._get_headers()
        response = await self.client.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
        if data.get("errno") != 0:
            errno = data.get("errno")
            message = data.get("errmsg", "Unknown error")
            raise _classify_errno(errno, message)
        return data

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
                "access_token": self.access_token,
            }
            data = await self._get_json(url, params)
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
            data = await self._get_json(url, params)
            return data.get("list", [])
        except Exception as e:
            logger.error(f"搜索文件失败 [{dir_path} / {key}]: {e}")
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
            logger.info(f'download_url of {file_path} : {download_url} ')
            # 下载文件
            response = await self.client.get(download_url, follow_redirects=True,
                params={
                    "access_token": self.access_token
                },
                headers={
                    "User-Agent": "pan.baidu.com"
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
            "dlink": 1,
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

        data = await self._get_json(url, params)

        # 返回第一个文件的dlink
        if "list" in data and len(data["list"]) > 0:
            return data["list"][0].get("dlink")

        # filemetas 成功但列表为空 → 该 fsid 不存在（确定性的 miss，映射 404）
        raise YunNotFoundError(-9, f"文件不存在: {file_path}")

    def _get_headers(self) -> dict:
        """构建请求头"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }
        return headers

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def close(self):
        """关闭客户端"""
        await self.client.aclose()
