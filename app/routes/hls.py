"""HLS路由 - 处理HLS相关的HTTP请求"""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import Response
import logging

from ..services.hls_proxy_service import HLSProxyService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hls", tags=["HLS"])

# 全局服务实例
hls_proxy_service: HLSProxyService = None

def init_service(service: HLSProxyService):
    """初始化服务"""
    global hls_proxy_service
    hls_proxy_service = service

@router.get("/{path:path}")
async def hls_proxy(path: str, request: Request):
    """
    HLS代理接口

    处理m3u8播放列表和分片文件的请求

    Args:
        path: 文件路径
        request: FastAPI请求对象

    Returns:
        文件内容
    """
    if not hls_proxy_service:
        raise HTTPException(status_code=500, detail="服务未初始化")

    # 构建完整路径
    request_path = f"/hls/{path}"

    # 判断文件类型
    if path.endswith('.m3u8'):
        return await hls_proxy_service.handle_m3u8_request(request_path)
    elif path.endswith('.ts'):
        return await hls_proxy_service.handle_chunk_request(request_path)
    else:
        # 根据Content-Type判断
        accept_header = request.headers.get('accept', '')
        if 'm3u8' in accept_header or 'mpegurl' in accept_header:
            return await hls_proxy_service.handle_m3u8_request(request_path)
        else:
            return await hls_proxy_service.handle_chunk_request(request_path)