"""HLS 路径与本地模式的共享工具。

hls 路由前缀、请求路径剥离、本地模式判断在各服务间重复，这里收敛成一份，
避免 segment_source / hls_proxy_service / metadata_service 各自维护。
"""
import os

# 路由前缀固定为 /hls（见 app/routes/hls.py => APIRouter(prefix=HLS_URL_PREFIX)）。
HLS_URL_PREFIX = "/hls"


def strip_hls_prefix(request_path: str) -> str:
    """去掉请求路径的 /hls 前缀，返回剩余部分（含前导 /）。"""
    if request_path.startswith(HLS_URL_PREFIX):
        return request_path[len(HLS_URL_PREFIX):]
    return request_path


def is_local_mode(local_path: str) -> bool:
    """本地模式是否启用：local_path 非空且为已存在目录。"""
    return bool(local_path) and os.path.isdir(local_path)
