from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    """应用配置"""
    app_name: str = "Yunpan HLS Proxy"
    app_version: str = "1.0.0"
    debug: bool = True

    # 服务配置
    host: str = "0.0.0.0"
    port: int = 8000

    # 百度网盘配置
    access_token: Optional[str] = None

    # 缓存配置
    cache_dir: str = "./cache"
    cache_ttl: int = 3600  # 缓存过期时间(秒)
    cache_segments: bool = False  # 是否缓存HLS分片文件 (默认: 不缓存)

    # HLS配置
    m3u8_path_prefix: str = "/hls"  # HLS文件路径前缀
    chunk_path_prefix: str = "/chunks"  # 分片文件路径前缀

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()