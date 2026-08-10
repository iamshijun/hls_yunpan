from pydantic_settings import BaseSettings
from pydantic import Field, AliasChoices
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
    cache_enabled: bool = True  # 是否启用磁盘缓存 (Vercel 等只读文件系统应设为 False)
    cache_segments: bool = False  # 是否缓存HLS分片文件 (默认: 不缓存)

    # Redis / Upstash (Vercel KV) 配置 - 用于跨实例存储 fsid
    # 兼容多种注入的环境变量名: 自定义 REDIS_URL / Vercel KV / Upstash Marketplace
    redis_url: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "REDIS_URL", "KV_REST_API_URL", "UPSTASH_REDIS_REST_URL"
        ),
    )
    redis_token: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "REDIS_TOKEN", "KV_REST_API_TOKEN", "UPSTASH_REDIS_REST_TOKEN"
        ),
    )

    # HLS配置
    yun_path_prefix: str = "/apps/movies"  # 网盘存储根路径（HLS 文件所在目录）

    # httpx 请求日志控制（默认关闭，避免打印请求URL等敏感信息）
    httpx_log: bool = False

    # 本地模式配置
    local_path: str = "./local_hls"  # 本地HLS文件存储目录，如果存在则自动启用本地模式

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()