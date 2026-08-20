"""Metadata 路由 - 提供 /metadata/{path}"""
import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from ..services.metadata_service import MetadataService
from ..services.baiduyun_service import YunAPIError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Metadata"])


def get_metadata_service(request: Request) -> MetadataService:
    """从应用状态获取 MetadataService（由 lifespan 注入）"""
    service = getattr(request.app.state, "metadata_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="服务未初始化")
    return service


@router.get("/metadata/{path:path}")
async def get_metadata(
    path: str,
    metadata_service: MetadataService = Depends(get_metadata_service),
):
    """读取 {path}/metadata.txt 并返回解析后的 JSON。

    文件不存在时返回 404（无 metadata 是合法场景，前端据此静默不显示面板）。
    """
    try:
        data = await metadata_service.get_metadata(path)
    except (YunAPIError, httpx.HTTPError) as e:
        # 上游 API 失败不是「没有 metadata」——返回 502，避免前端误以为文件不存在
        logger.warning(f"metadata 上游错误 [{path}]: {e}")
        raise HTTPException(status_code=502, detail=f"网盘服务不可用: {e}")
    if data is None:
        raise HTTPException(status_code=404, detail="metadata not found")
    return data
