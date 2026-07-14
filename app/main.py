"""主应用入口"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config.settings import settings
from app.services.baiduyun_service import BaiduYunService
from app.services.cache_service import CacheService
from app.services.hls_proxy_service import HLSProxyService
from app.routes import health, hls

# 配置日志
logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 全局服务实例
yun_service: BaiduYunService = None
cache_service: CacheService = None
hls_proxy_service: HLSProxyService = None


@asynccontextmanager
async def lifespan(app):
    """应用生命周期管理"""
    # 启动时初始化
    global yun_service, cache_service, hls_proxy_service

    logger.info("正在初始化服务...")

    # 初始化百度网盘服务
    yun_service = BaiduYunService(
        access_token=settings.access_token
    )

    # 初始化缓存服务
    cache_service = CacheService(
        cache_dir=settings.cache_dir,
        ttl=settings.cache_ttl
    )

    # 初始化HLS代理服务
    hls_proxy_service = HLSProxyService(
        yun_service=yun_service,
        cache_service=cache_service,
        hls_root_path=settings.m3u8_path_prefix,
        cache_segments=settings.cache_segments
    )

    # 初始化路由服务
    hls.init_service(hls_proxy_service)

    logger.info("服务初始化完成")

    yield

    # 关闭时清理
    logger.info("正在关闭服务...")
    await yun_service.close()
    logger.info("服务已关闭")


# 创建FastAPI应用
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(health.router)
app.include_router(hls.router)

# 挂载静态文件服务
static_dir = Path(__file__).parent.parent / "web"
if static_dir.exists():
    app.mount("/web", StaticFiles(directory=str(static_dir)), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info",
        timeout_keep_alive=30,
    )