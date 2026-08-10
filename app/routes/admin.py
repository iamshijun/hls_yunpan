"""管理路由"""
import logging
from fastapi import APIRouter, Query

router = APIRouter(prefix="/admin", tags=["Admin"])

_HTTPX_LOGGERS = ("httpx", "httpcore")


def _get_httpx_log_enabled() -> bool:
    """读取当前 httpx 日志是否开启（任一 logger 为 DEBUG 即视为开启）"""
    return logging.getLogger("httpx").level == logging.DEBUG


def _set_httpx_log(enabled: bool) -> None:
    """动态开关 httpx / httpcore 的日志级别"""
    from logging import DEBUG, WARNING
    level = DEBUG if enabled else WARNING
    for name in _HTTPX_LOGGERS:
        logging.getLogger(name).setLevel(level)


@router.get("/httpx-log")
async def get_httpx_log():
    """查看 httpx 日志开关状态"""
    return {
        "httpx_log_enabled": _get_httpx_log_enabled(),
        "note": "Use POST /admin/httpx-log?enable=true to enable, ?enable=false to disable",
    }


@router.post("/httpx-log")
async def toggle_httpx_log(enable: bool = Query(..., description="true=开启, false=关闭")):
    """动态开关 httpx 请求日志（无需重启）"""
    _set_httpx_log(enable)
    return {
        "httpx_log_enabled": enable,
        "message": f"httpx 请求日志已{'开启' if enable else '关闭'}",
    }
