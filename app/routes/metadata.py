"""Metadata 路由 - 提供 /metadata/{path}"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request

from ..services.metadata_service import MetadataService

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
    data = await metadata_service.get_metadata(path)
    if data is None:
        raise HTTPException(status_code=404, detail="metadata not found")
    return data
