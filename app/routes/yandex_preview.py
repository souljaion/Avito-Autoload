"""Proxy for Yandex.Disk preview images.

Yandex CDN blocks direct browser requests (hotlink/Referer protection).
This endpoint fetches previews server-to-server and streams them to the browser.
"""

from urllib.parse import urlparse

import httpx
import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["yandex-preview"])

_PREVIEW_ALLOWED_HOSTS = {
    "downloader.disk.yandex.ru",
    "downloader.yandex.ru",
}


@router.get("/api/yandex-preview")
async def yandex_preview(url: str):
    """Proxy a Yandex.Disk preview image to avoid hotlink 403 in browsers."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return JSONResponse({"error": "https required"}, status_code=400)
    if parsed.hostname not in _PREVIEW_ALLOWED_HOSTS:
        return JSONResponse({"error": "host not allowed"}, status_code=400)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.warning("yandex_preview.upstream_error", status=e.response.status_code, url=url[:80])
        return JSONResponse({"error": "upstream error"}, status_code=502)
    except (httpx.TimeoutException, httpx.ConnectError):
        return JSONResponse({"error": "timeout"}, status_code=504)

    content_type = resp.headers.get("content-type", "image/jpeg")
    if not content_type.startswith("image/"):
        return JSONResponse({"error": "not an image"}, status_code=400)

    return Response(
        content=resp.content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )
