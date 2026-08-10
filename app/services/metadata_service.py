"""Metadata 服务

编排元数据文件的读取：
- 本地模式：直接读取本地 metadata.txt
- 云模式：通过 search API 定位文件 → fsid → download → parse
"""
import logging
import os
from typing import Any, Dict, Optional

from .baiduyun_service import BaiduYunService
from ..utils.metadata_parser import parse_metadata

logger = logging.getLogger(__name__)

METADATA_FILENAME = "metadata.txt"


class MetadataService:
    """根据 clean_path 读取对应的 metadata.txt。"""

    def __init__(
        self,
        yun_service: BaiduYunService,
        yun_path_prefix: str,
        local_path: str,
    ):
        self.yun = yun_service
        self.yun_prefix = yun_path_prefix.rstrip("/")
        self.local_mode = bool(local_path) and os.path.isdir(local_path)
        self.local_path = local_path

    async def get_metadata(self, clean_path: str) -> Optional[Dict[str, Any]]:
        """根据路径获取元数据。

        Args:
            clean_path: 不含开头 `/` 的相对路径（如 `hdsn-006` 或 `movies/abc`）

        Returns:
            解析后的字段 dict；文件不存在 / 读取失败时返回 None。
        """
        clean_path = clean_path.strip().lstrip("/").rstrip("/")
        if not clean_path:
            return None

        rel = f"{clean_path}/{METADATA_FILENAME}"

        if self.local_mode:
            return self._read_local(rel)

        # 云模式：搜索 + 精确匹配文件名（避免搜到别的目录下的同名文件）
        yun_dir = f"{self.yun_prefix}/{clean_path}"
        try:
            files = await self.yun.search_file(key=METADATA_FILENAME, dir_path=yun_dir)
        except Exception as e:
            logger.error(f"search metadata 失败 [{yun_dir}]: {e}")
            return None

        match = next(
            (f for f in files if os.path.basename(f.get("path", "")) == METADATA_FILENAME),
            None,
        )
        if not match:
            return None

        fsid = match.get("fs_id")
        path = match.get("path")
        try:
            content = await self.yun.download_file(path, fsid=fsid)
        except Exception as e:
            logger.error(f"下载 metadata 失败 [{path}]: {e}")
            return None

        try:
            return parse_metadata(content.decode("utf-8", errors="replace"))
        except Exception as e:
            logger.error(f"解析 metadata 失败 [{path}]: {e}")
            return None

    def _read_local(self, rel: str) -> Optional[Dict[str, Any]]:
        path = os.path.join(self.local_path, rel)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return parse_metadata(f.read())
        except Exception as e:
            logger.error(f"读取本地 metadata 失败 [{path}]: {e}")
            return None
