"""保留 ASGI 启动方式：uvicorn api:app。"""

from web.api import app


__all__ = ["app"]
