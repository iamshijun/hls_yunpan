"""缓存服务 - 负责缓存网盘文件和元数据到本地"""
import aiofiles
import asyncio
import json
import os
from pathlib import Path
from typing import Optional, Dict
import logging
import hashlib
import time

logger = logging.getLogger(__name__)

class CacheService:
    """本地缓存服务类"""

    def __init__(self, cache_dir: str = "./cache", ttl: int = 3600):
        self.cache_dir = Path(cache_dir)
        self.ttl = ttl
        self.locks = {}  # 文件锁
        self.fsid_cache: Dict[str, Dict[str, Dict]] = {}  # fsid内存缓存: {dir_path: {file_path: fsid_info}}

        # 创建缓存目录
        self.cache_dir.mkdir(parents=True, exist_ok=True)

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

    def _get_fsid_cache_path(self, dir_path: str) -> Path:
        """获取指定目录的fsid缓存文件路径"""
        # 使用目录路径的hash作为文件名
        dir_hash = hashlib.md5(dir_path.encode()).hexdigest()
        return self.cache_dir / "fsid_cache" / f"{dir_hash}.json"

    async def _load_fsid_cache(self, dir_path: str) -> Dict:
        """从磁盘加载指定目录的fsid缓存"""
        cache_path = self._get_fsid_cache_path(dir_path)
        if cache_path.exists():
            try:
                async with aiofiles.open(cache_path, 'r') as f:
                    content = await f.read()
                    data = json.loads(content)
                    return data
            except Exception as e:
                logger.error(f"加载fsid缓存失败 [{dir_path}]: {e}")
        return {}

    async def _save_fsid_cache(self, dir_path: str):
        """保存指定目录的fsid缓存到磁盘"""
        cache_path = self._get_fsid_cache_path(dir_path)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = self.fsid_cache.get(dir_path, {})
            async with aiofiles.open(cache_path, 'w') as f:
                await f.write(json.dumps(data, ensure_ascii=False))
            logger.info(f"保存fsid缓存 [{dir_path}]: {len(data)} 条记录")
        except Exception as e:
            logger.error(f"保存fsid缓存失败 [{dir_path}]: {e}")

    async def get_fsid(self, file_path: str) -> Optional[int]:
        """
        获取文件的fsid

        Args:
            file_path: 文件路径

        Returns:
            fsid或None
        """
        # 获取文件所在目录
        dir_path = os.path.dirname(file_path) or "/"

        # 检查内存缓存
        if dir_path not in self.fsid_cache:
            # 从磁盘加载
            self.fsid_cache[dir_path] = await self._load_fsid_cache(dir_path)

        dir_cache = self.fsid_cache.get(dir_path, {})
        info = dir_cache.get(file_path)
        if info:
            # 检查是否过期
            if time.time() - info.get("timestamp", 0) < self.ttl:
                logger.info(f"fsid缓存命中: {file_path} -> {info['fsid']}")
                return info.get("fsid")
            else:
                # 过期则删除
                del dir_cache[file_path]

        return None

    async def set_fsid(self, file_path: str, fsid: int) -> None:
        """
        设置文件的fsid

        Args:
            file_path: 文件路径
            fsid: 文件系统ID
        """
        # 获取文件所在目录
        dir_path = os.path.dirname(file_path) or "/"

        # 初始化目录缓存
        if dir_path not in self.fsid_cache:
            self.fsid_cache[dir_path] = await self._load_fsid_cache(dir_path)

        self.fsid_cache[dir_path][file_path] = {
            "fsid": fsid,
            "timestamp": time.time()
        }

        # 异步保存
        asyncio.create_task(self._save_fsid_cache(dir_path))

        logger.info(f"fsid缓存已写入: {file_path} -> {fsid}")

    async def set_fsids(self, dir_path: str, fsid_map: Dict[str, int]) -> None:
        """
        批量设置fsid映射

        Args:
            dir_path: 目录路径
            fsid_map: {file_path: fsid}
        """
        # 初始化目录缓存
        if dir_path not in self.fsid_cache:
            self.fsid_cache[dir_path] = await self._load_fsid_cache(dir_path)

        timestamp = time.time()
        for file_path, fsid in fsid_map.items():
            self.fsid_cache[dir_path][file_path] = {
                "fsid": fsid,
                "timestamp": timestamp
            }

        # 异步保存
        asyncio.create_task(self._save_fsid_cache(dir_path))

        logger.info(f"批量fsid缓存已写入 [{dir_path}]: {len(fsid_map)} 条记录")

    async def clear_dir_fsid_cache(self, dir_path: str) -> None:
        """
        清理指定目录的fsid缓存

        Args:
            dir_path: 目录路径
        """
        if dir_path in self.fsid_cache:
            del self.fsid_cache[dir_path]

        cache_path = self._get_fsid_cache_path(dir_path)
        if cache_path.exists():
            try:
                cache_path.unlink()
                logger.info(f"已清理目录fsid缓存: {dir_path}")
            except Exception as e:
                logger.error(f"清理目录fsid缓存失败 [{dir_path}]: {e}")

    async def is_valid(self, path: str) -> bool:
        """
        检查缓存是否有效

        Args:
            path: 原始路径

        Returns:
            是否有效
        """
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
        清理过期缓存

        Returns:
            清理的文件数量
        """
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

            # 清理过期的fsid缓存
            fsid_cache_dir = self.cache_dir / "fsid_cache"
            if fsid_cache_dir.exists():
                for cache_file in fsid_cache_dir.glob("*.json"):
                    try:
                        async with aiofiles.open(cache_file, 'r') as f:
                            content = await f.read()
                            data = json.loads(content)

                        # 检查是否所有记录都过期
                        now = time.time()
                        all_expired = all(
                            now - info.get("timestamp", 0) >= self.ttl
                            for info in data.values()
                        )

                        if all_expired:
                            cache_file.unlink()
                            count += 1
                            logger.info(f"清理过期fsid缓存: {cache_file.name}")
                    except Exception as e:
                        logger.error(f"清理fsid缓存失败 [{cache_file}]: {e}")

            logger.info(f"清理了 {count} 个过期缓存")
        except Exception as e:
            logger.error(f"清理过期缓存失败: {e}")

        return count