"""fsid 存储抽象

fsid 是百度网盘文件的唯一 id（file_path -> fsid），属于体积小、读多写少的
元数据，非常适合用 KV 存储。这里抽象出 FsidStore 接口，提供三种后端：

- MemoryFsidStore: 纯内存，进程/热实例生命周期内有效（无持久化）
- DiskFsidStore:   本地磁盘 JSON（按目录分文件），带内存 L1
- RedisFsidStore:  Redis / Upstash（Vercel KV），跨实例、跨冷启动共享

本地与 Vercel 共用同一套代码，仅通过配置切换后端。
"""
import os
import json
import time
import asyncio
import hashlib
import inspect
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Dict

import aiofiles

logger = logging.getLogger(__name__)


class FsidStore(ABC):
    """fsid 存储后端接口"""

    @abstractmethod
    async def get(self, file_path: str) -> Optional[int]:
        """获取文件 fsid，不存在或过期返回 None"""
        ...

    @abstractmethod
    async def set(self, file_path: str, fsid: int) -> None:
        """写入单个文件的 fsid"""
        ...

    @abstractmethod
    async def set_many(self, fsid_map: Dict[str, int]) -> None:
        """批量写入 {file_path: fsid}"""
        ...

    async def close(self) -> None:
        """释放底层资源（默认无操作）"""
        return


class MemoryFsidStore(FsidStore):
    """纯内存 fsid 存储"""

    def __init__(self, ttl: int = 3600):
        self.ttl = ttl
        self._data: Dict[str, Dict] = {}  # {file_path: {"fsid":.., "timestamp":..}}

    async def get(self, file_path: str) -> Optional[int]:
        info = self._data.get(file_path)
        if not info:
            return None
        if time.time() - info.get("timestamp", 0) < self.ttl:
            return info.get("fsid")
        # 过期
        self._data.pop(file_path, None)
        return None

    async def set(self, file_path: str, fsid: int) -> None:
        self._data[file_path] = {"fsid": fsid, "timestamp": time.time()}

    async def set_many(self, fsid_map: Dict[str, int]) -> None:
        now = time.time()
        for fp, fsid in fsid_map.items():
            self._data[fp] = {"fsid": fsid, "timestamp": now}


class DiskFsidStore(FsidStore):
    """本地磁盘 fsid 存储（按目录分 JSON 文件，带内存 L1）

    保持与旧实现相同的磁盘布局：{cache_dir}/fsid_cache/{md5(dir)}.json
    """

    def __init__(self, cache_dir: str, ttl: int = 3600):
        self.cache_dir = Path(cache_dir)
        self.ttl = ttl
        self._mem: Dict[str, Dict[str, Dict]] = {}  # {dir_path: {file_path: info}}

    def _dir_cache_path(self, dir_path: str) -> Path:
        dir_hash = hashlib.md5(dir_path.encode()).hexdigest()
        return self.cache_dir / "fsid_cache" / f"{dir_hash}.json"

    async def _load_dir(self, dir_path: str) -> Dict:
        if dir_path in self._mem:
            return self._mem[dir_path]
        path = self._dir_cache_path(dir_path)
        data: Dict = {}
        if path.exists():
            try:
                async with aiofiles.open(path, "r") as f:
                    data = json.loads(await f.read())
            except Exception as e:
                logger.error(f"加载fsid缓存失败 [{dir_path}]: {e}")
        self._mem[dir_path] = data
        return data

    async def _save_dir(self, dir_path: str) -> None:
        path = self._dir_cache_path(dir_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = self._mem.get(dir_path, {})
            async with aiofiles.open(path, "w") as f:
                await f.write(json.dumps(data, ensure_ascii=False))
            logger.info(f"保存fsid缓存 [{dir_path}]: {len(data)} 条记录")
        except Exception as e:
            logger.error(f"保存fsid缓存失败 [{dir_path}]: {e}")

    async def get(self, file_path: str) -> Optional[int]:
        dir_path = os.path.dirname(file_path) or "/"
        data = await self._load_dir(dir_path)
        info = data.get(file_path)
        if not info:
            return None
        if time.time() - info.get("timestamp", 0) < self.ttl:
            return info.get("fsid")
        del data[file_path]
        return None

    async def set(self, file_path: str, fsid: int) -> None:
        dir_path = os.path.dirname(file_path) or "/"
        data = await self._load_dir(dir_path)
        data[file_path] = {"fsid": fsid, "timestamp": time.time()}
        asyncio.create_task(self._save_dir(dir_path))

    async def set_many(self, fsid_map: Dict[str, int]) -> None:
        now = time.time()
        touched = set()
        for fp, fsid in fsid_map.items():
            dir_path = os.path.dirname(fp) or "/"
            data = await self._load_dir(dir_path)
            data[fp] = {"fsid": fsid, "timestamp": now}
            touched.add(dir_path)
        for dir_path in touched:
            asyncio.create_task(self._save_dir(dir_path))


class RedisFsidStore(FsidStore):
    """Redis / Upstash（Vercel KV）fsid 存储

    存储模型：每个目录一个 Redis Hash，key = fsid:{md5(dir)}，
    field = file_path，value = fsid，整个 key 设置 TTL。
    这样批量写入（一个目录）只需一次 HSET + 一次 EXPIRE，round-trip 最少。
    附带一个进程内 L1（MemoryFsidStore），减少热实例内的重复请求。
    """

    def __init__(self, url: str, token: str, ttl: int = 3600):
        from upstash_redis.asyncio import Redis  # 延迟导入，本地未装包也不影响

        self._redis = Redis(url=url, token=token)
        self.ttl = ttl
        self._l1 = MemoryFsidStore(ttl=ttl)

    @staticmethod
    def _dir_key(dir_path: str) -> str:
        return "fsid:" + hashlib.md5(dir_path.encode()).hexdigest()

    async def get(self, file_path: str) -> Optional[int]:
        # L1 命中
        cached = await self._l1.get(file_path)
        if cached is not None:
            return cached

        dir_key = self._dir_key(os.path.dirname(file_path) or "/")
        try:
            raw = await self._redis.hget(dir_key, file_path)
        except Exception as e:
            logger.error(f"Redis 读取 fsid 失败 [{file_path}]: {e}")
            return None
        if raw is None:
            return None
        try:
            fsid = int(raw)
        except (ValueError, TypeError):
            return None
        await self._l1.set(file_path, fsid)
        return fsid

    async def set(self, file_path: str, fsid: int) -> None:
        dir_path = os.path.dirname(file_path) or "/"
        dir_key = self._dir_key(dir_path)
        try:
            await self._redis.hset(dir_key, field=file_path, value=fsid)
            await self._redis.expire(dir_key, self.ttl)
        except Exception as e:
            logger.error(f"Redis 写入 fsid 失败 [{file_path}]: {e}")
        await self._l1.set(file_path, fsid)

    async def set_many(self, fsid_map: Dict[str, int]) -> None:
        # 按目录分组，一个目录一次 HSET
        by_dir: Dict[str, Dict[str, int]] = {}
        for fp, fsid in fsid_map.items():
            by_dir.setdefault(os.path.dirname(fp) or "/", {})[fp] = fsid

        for dir_path, mapping in by_dir.items():
            dir_key = self._dir_key(dir_path)
            try:
                await self._redis.hset(dir_key, values=mapping)
                await self._redis.expire(dir_key, self.ttl)
                logger.info(f"Redis 批量写入 fsid [{dir_path}]: {len(mapping)} 条")
            except Exception as e:
                logger.error(f"Redis 批量写入 fsid 失败 [{dir_path}]: {e}")

        await self._l1.set_many(fsid_map)

    async def close(self) -> None:
        close = getattr(self._redis, "close", None)
        if close is None:
            return
        try:
            result = close()
            if inspect.isawaitable(result):
                await result
        except Exception as e:
            logger.warning(f"关闭 Redis 连接失败: {e}")


def create_fsid_store(
    ttl: int = 3600,
    cache_enabled: bool = True,
    cache_dir: str = "./cache",
    redis_url: Optional[str] = None,
    redis_token: Optional[str] = None,
) -> FsidStore:
    """根据配置选择合适的 fsid 存储后端。

    优先级: Redis > 磁盘(cache_enabled) > 内存
    """
    if redis_url and redis_token:
        logger.info("fsid 存储后端: Redis (Upstash / Vercel KV)")
        return RedisFsidStore(redis_url, redis_token, ttl=ttl)
    if cache_enabled:
        logger.info("fsid 存储后端: 本地磁盘")
        return DiskFsidStore(cache_dir, ttl=ttl)
    logger.info("fsid 存储后端: 内存")
    return MemoryFsidStore(ttl=ttl)