"""Yandex.Disk public folder API client.

Downloads files from shared (public) Yandex.Disk folders.
No OAuth required — uses the public resources API.
"""

import asyncio
import re
from urllib.parse import urlparse, quote

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

_VALID_HOSTS = {"disk.yandex.ru", "yadi.sk", "disk.yandex.com", "disk.yandex.by", "disk.yandex.kz"}


class RateLimitError(Exception):
    """Yandex.Disk API returned 429 — retry later."""


def extract_public_key(public_url: str) -> str:
    """Validate and return the public URL (Yandex API accepts full URL as public_key).

    Raises ValueError on obviously invalid input.
    """
    url = public_url.strip()
    if not url:
        raise ValueError("Empty URL")
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise ValueError(f"Invalid scheme: {parsed.scheme}")
    if parsed.hostname not in _VALID_HOSTS:
        raise ValueError(f"Not a Yandex.Disk URL: {parsed.hostname}")
    if not parsed.path or len(parsed.path) < 3:
        raise ValueError("URL path too short")
    path = parsed.path.lstrip("/")
    if not path.startswith(("d/", "i/")):
        raise ValueError(
            "Это не публичная ссылка Яндекс.Диска. "
            "Откройте папку в Я.Диске, нажмите «Поделиться» → «Скопировать ссылку». "
            "Ссылка должна начинаться с https://disk.yandex.ru/d/..."
        )
    return url


async def list_folder(public_url: str, path: str = "/") -> list[dict]:
    """List image files in a public Yandex.Disk folder.

    Returns list of dicts: {name, path, size, mime_type, md5, preview_url}.
    Only image files (mime_type starts with 'image/') are returned.
    """
    public_key = extract_public_key(public_url)
    params = {
        "public_key": public_key,
        "path": path,
        "preview_size": "L",
        "limit": 200,
    }
    async with httpx.AsyncClient(timeout=settings.YANDEX_DOWNLOAD_TIMEOUT) as client:
        resp = await client.get(
            f"{settings.YANDEX_DISK_API_BASE}/resources",
            params=params,
        )
    _check_response(resp, public_url)
    data = resp.json()

    embedded = data.get("_embedded", {})
    items = embedded.get("items", [])

    files = []
    for item in items:
        if item.get("type") != "file":
            continue
        mime = item.get("mime_type", "")
        if not mime.startswith("image/"):
            continue
        files.append({
            "name": item.get("name", ""),
            "path": item.get("path", ""),
            "size": item.get("size", 0),
            "mime_type": mime,
            "md5": item.get("md5", ""),
            "preview_url": item.get("preview", ""),
        })

    files.sort(key=lambda f: f["name"])
    return files


async def get_download_url(public_url: str, path: str) -> str:
    """Get a one-time direct download URL for a file in a public folder.

    The returned URL is short-lived (~hours).
    """
    public_key = extract_public_key(public_url)
    params = {"public_key": public_key, "path": path}
    async with httpx.AsyncClient(timeout=settings.YANDEX_DOWNLOAD_TIMEOUT) as client:
        resp = await client.get(
            f"{settings.YANDEX_DISK_API_BASE}/resources/download",
            params=params,
        )
    _check_response(resp, public_url)
    data = resp.json()
    href = data.get("href")
    if not href:
        raise ValueError("No download URL in response")
    return href


async def download_file(public_url: str, path: str, dest_path: str) -> int:
    """Download a file from a public Yandex.Disk folder to dest_path.

    Streams to disk (64 KB chunks) to avoid loading the whole file in RAM.
    Returns file size in bytes.
    """
    href = await get_download_url(public_url, path)
    total = 0
    async with httpx.AsyncClient(timeout=settings.YANDEX_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
        async with client.stream("GET", href) as resp:
            resp.raise_for_status()
            with open(dest_path, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    f.write(chunk)
                    total += len(chunk)

    logger.info("yandex_disk.downloaded", path=path, size_kb=total // 1024)
    return total


def _check_response(resp: httpx.Response, public_url: str):
    """Check HTTP response and raise appropriate exceptions."""
    if resp.status_code == 404:
        raise ValueError("Folder not found or not public")
    if resp.status_code == 429:
        raise RateLimitError("Yandex.Disk rate limit exceeded")
    resp.raise_for_status()
