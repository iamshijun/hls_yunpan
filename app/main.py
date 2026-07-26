"""主应用入口"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config.settings import settings
from app.services.baiduyun_service import BaiduYunService
from app.services.cache_service import CacheService
from app.services.hls_proxy_service import HLSProxyService
from app.routes import health, hls

logger = logging.getLogger(__name__)


def create_app(
    cache_dir: Optional[str] = None,
    docs_enabled: Optional[bool] = None,
    static_dir: Optional[Path] = None,
) -> FastAPI:
    """创建并配置FastAPI应用实例

    Args:
        cache_dir: 缓存目录，默认使用 settings.cache_dir
        docs_enabled: 是否启用 API 文档，默认等于 settings.debug
        static_dir: 静态文件目录，默认使用项目根目录的 web/ 文件夹
    """
    if docs_enabled is None:
        docs_enabled = settings.debug

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """应用生命周期管理"""
        logger.info("正在初始化服务...")
        yun_svc = BaiduYunService(access_token=settings.access_token)
        cache_svc = CacheService(
            cache_dir=cache_dir or settings.cache_dir,
            ttl=settings.cache_ttl
        )
        hls_svc = HLSProxyService(
            yun_service=yun_svc,
            cache_service=cache_svc,
            hls_root_path=settings.m3u8_path_prefix,
            cache_segments=settings.cache_segments,
            local_path=settings.local_path
        )
        hls.init_service(hls_svc)
        logger.info("服务初始化完成")
        yield
        await yun_svc.close()
        logger.info("服务已关闭")

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 静态文件
    effective_static_dir = static_dir or (Path(__file__).parent.parent / "web")
    if effective_static_dir.exists():
        app.mount(
            "/web",
            StaticFiles(directory=str(effective_static_dir)),
            name="web",
        )
        logger.info(f"静态文件已挂载到 /web: {effective_static_dir}")
    else:
        logger.warning("Web目录不存在，静态文件服务已禁用")

    # 路由
    app.include_router(health.router)
    app.include_router(hls.router)

    return app


# 标准应用实例（本地运行 / Vercel 共享同一实例）
app = create_app()


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO if not settings.debug else logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info",
        timeout_keep_alive=30,
    )