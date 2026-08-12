"""目录 API 代理 - 把浏览器请求转发到外部「影片目录 API」。

设计要点：
- base 只来自配置（settings.catalog_api_base），不接受客户端传入，避免变成开放代理。
- 如果配置了 settings.catalog_api_token，转发时加 `Authorization: Bearer <token>`。
- 复用 lifespan 里建好的 `httpx.AsyncClient`（注入到 app.state.http_client），
  避免每次新建连接。
"""
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from config.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/catalog", tags=["Catalog"])


def _get_client(request: Request) -> httpx.AsyncClient:
    """从应用状态获取共享的 httpx 客户端（由 lifespan 注入）。"""
    client: Optional[httpx.AsyncClient] = getattr(request.app.state, "http_client", None)
    if client is None:
        raise HTTPException(status_code=500, detail="HTTP 客户端未初始化")
    return client


@router.get("/{path:path}")
async def proxy(path: str, request: Request):
    """转发 GET 请求到外部目录 API。

    透传除 `_base` 之外的所有查询参数；上游 base 强制走 settings。
    """
    base = settings.catalog_api_base.rstrip("/")
    params = [(k, v) for k, v in request.query_params.multi_items() if k != "_base"]
    url = f"{base}/{path.lstrip('/')}"

    headers = {}
    if settings.catalog_api_token:
        headers["Authorization"] = f"Bearer {settings.catalog_api_token}"

    client = _get_client(request)
    try:
        upstream = await client.get(url, params=params, headers=headers)
    except httpx.HTTPError as e:
        logger.warning("目录 API 不可达: %s", e)
        raise HTTPException(status_code=502, detail=f"目录 API 不可达: {e}")

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
    )
