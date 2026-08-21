"""健康检查路由"""
from fastapi import APIRouter

from config.settings import settings

router = APIRouter(tags=["Health"])

@router.get("/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "ok",
        "service": settings.app_name,
        "message": "服务运行正常"
    }

@router.get("/")
async def root():
    """根路径"""
    return {
        "service": settings.app_name,
        "description": "HLS媒体文件代理服务 - 使用网盘作为存储",
        "version": settings.app_version,
        "endpoints": {
            "health": "/health",
            "hls_proxy": "/hls/{path:path}",
            "httpx_log": "/admin/httpx-log",
        }
    }
