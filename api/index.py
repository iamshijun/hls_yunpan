"""Vercel Serverless 入口

Vercel 的 @vercel/python 运行时会直接托管此处导出的 ASGI `app`，
与本地运行使用的是同一个应用实例，保证行为一致。

Vercel 环境差异（如缓存目录、DEBUG）通过项目环境变量配置，例如：
    ACCESS_TOKEN=...
    CACHE_DIR=/tmp/cache
    DEBUG=false
"""
from app.main import app

__all__ = ["app"]