"""健康检查路由"""
from fastapi import APIRouter

router = APIRouter(tags=["Health"])

@router.get("/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "ok",
        "service": "yunpan-hls-proxy",
        "message": "服务运行正常"
    }

@router.get("/")
async def root():
    """根路径"""
    return {
        "service": "yunpan-hls-proxy",
        "description": "HLS媒体文件代理服务 - 使用网盘作为存储",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "hls_proxy": "/hls/{path:path}"
        }
    }