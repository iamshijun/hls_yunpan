"""缓存服务 - 负责缓存网盘文件内容，并委托 fsid 存储"""
import aiofiles
import asyncio
import json
from pathlib import Path
from typing import Optional, Dict
import logging
import hashlib
import time

from .fsid_store import FsidStore, DiskFsidStore, MemoryFsidStore

logger = logging.getLogger(__name__)

class CacheService:
    """本地缓存服务类

    职责：
    - 文件内容缓存（get/set，受 enabled 控制是否落盘）
    - fsid 缓存：委托给注入的 FsidStore（内存/磁盘/Redis）
    """

    def __init__(
        self,
        cache_dir: str = "./cache",
        ttl: int = 3600,
        enabled: bool = True,
        fsid_store: Optional[FsidStore] = None,
    ):
        """
        Args:
            cache_dir: 缓存目录
            ttl: 缓存过期时间(秒)
            enabled: 是否启用磁盘缓存。为 False 时（如 Vercel 只读文件系统）
                     跳过所有文件内容磁盘读写。
            fsid_store: fsid 存储后端。未提供时按 enabled 选择磁盘/内存。
        """
        self.cache_dir = Path(cache_dir)
        self.ttl = ttl
        self.enabled = enabled
        self.locks = {}  # 文件锁

        # fsid 存储后端（可注入 Redis 等）
        if fsid_store is not None:
            self.fsid_store = fsid_store
        elif enabled:
            self.fsid_store = DiskFsidStore(cache_dir, ttl=ttl)
        else:
            self.fsid_store = MemoryFsidStore(ttl=ttl)

        # 创建缓存目录（仅在启用磁盘缓存时）
        if self.enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        else:
            logger.info("磁盘缓存已禁用，文件内容不落盘")

    async def close(self) -> None:
        """释放资源（关闭 fsid 存储的底层连接）"""
        await self.fsid_store.close()

    def _get_cache_key(self, path: str) -> str:
        """生成缓存键"""
        return hashlib.md5(path.encode()).hexdigest()

    def _get_cache_path(self, path: str) -> Path:
        """获取缓存文件路径"""
        cache_key = self._get_cache_key(path)
        return self.cache_dir / cache_key[:2] / cache_key

    def _get_meta_path(self, path: str) -> Path:
        """获取元数据文件路径"""
        return self._get_cache_path(path).with_suffix(".meta")

    # ---- fsid 缓存：全部委托给 fsid_store ----

    async def get_fsid(self, file_path: str) -> Optional[int]:
        """获取文件的fsid，不存在返回None"""
        fsid = await self.fsid_store.get(file_path)
        if fsid is not None:
            logger.info(f"fsid缓存命中: {file_path} -> {fsid}")
        return fsid

    async def set_fsid(self, file_path: str, fsid: int) -> None:
        """设置文件的fsid"""
        await self.fsid_store.set(file_path, fsid)
        logger.info(f"fsid缓存已写入: {file_path} -> {fsid}")

    async def set_fsids(self, dir_path: str, fsid_map: Dict[str, int]) -> None:
        """批量设置fsid映射 {file_path: fsid}"""
        await self.fsid_store.set_many(fsid_map)
        logger.info(f"批量fsid缓存已写入 [{dir_path}]: {len(fsid_map)} 条记录")

    async def is_valid(self, path: str) -> bool:
        """
        检查缓存是否有效

        Args:
            path: 原始路径

        Returns:
            是否有效
        """
        if not self.enabled:
            return False
        meta_path = self._get_meta_path(path)
        if not meta_path.exists():
            return False

        try:
            async with aiofiles.open(meta_path, 'r') as f:
                content = await f.read()
                meta = json.loads(content)

            # 检查是否过期
            return time.time() - meta.get("timestamp", 0) < self.ttl
        except Exception as e:
            logger.error(f"检查缓存有效性失败: {e}")
            return False

    async def get(self, path: str) -> Optional[bytes]:
        """
        获取缓存内容

        Args:
            path: 原始路径

        Returns:
            缓存内容或None
        """
        if not await self.is_valid(path):
            return None

        cache_path = self._get_cache_path(path)
        if not cache_path.exists():
            return None

        try:
            async with aiofiles.open(cache_path, 'rb') as f:
                content = await f.read()
            logger.info(f"缓存命中: {path}")
            return content
        except Exception as e:
            logger.error(f"读取缓存失败: {e}")
            return None

    async def set(self, path: str, content: bytes) -> None:
        """
        设置缓存

        Args:
            path: 原始路径
            content: 缓存内容
        """
        if not self.enabled:
            return
        cache_path = self._get_cache_path(path)
        meta_path = self._get_meta_path(path)

        # 创建目录
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # 获取锁
            lock_key = self._get_cache_key(path)
            if lock_key not in self.locks:
                self.locks[lock_key] = asyncio.Lock()

            async with self.locks[lock_key]:
                # 写入文件
                async with aiofiles.open(cache_path, 'wb') as f:
                    await f.write(content)

                # 写入元数据
                meta = {
                    "path": path,
                    "timestamp": time.time(),
                    "size": len(content)
                }
                async with aiofiles.open(meta_path, 'w') as f:
                    await f.write(json.dumps(meta))

                logger.info(f"缓存已写入: {path} ({len(content)} bytes)")
        except Exception as e:
            logger.error(f"写入缓存失败: {e}")
            raise

    async def delete(self, path: str) -> None:
        """
        删除缓存

        Args:
            path: 原始路径
        """
        cache_path = self._get_cache_path(path)
        meta_path = self._get_meta_path(path)

        try:
            if cache_path.exists():
                cache_path.unlink()
            if meta_path.exists():
                meta_path.unlink()
            logger.info(f"缓存已删除: {path}")
        except Exception as e:
            logger.error(f"删除缓存失败: {e}")

    async def clear_expired(self) -> int:
        """
        清理过期的文件内容缓存（fsid 过期由 fsid_store 自行管理）

        Returns:
            清理的文件数量
        """
        if not self.enabled:
            return 0
        count = 0
        try:
            # 清理文件缓存
            for meta_path in self.cache_dir.rglob("*.meta"):
                try:
                    async with aiofiles.open(meta_path, 'r') as f:
                        content = await f.read()
                        meta = json.loads(content)

                    # 检查是否过期
                    if time.time() - meta.get("timestamp", 0) >= self.ttl:
                        cache_path = meta_path.with_suffix("")
                        if cache_path.exists():
                            cache_path.unlink()
                        meta_path.unlink()
                        count += 1
                except Exception as e:
                    logger.error(f"清理缓存失败 [{meta_path}]: {e}")

            logger.info(f"清理了 {count} 个过期缓存")
        except Exception as e:
            logger.error(f"清理过期缓存失败: {e}")

        return count