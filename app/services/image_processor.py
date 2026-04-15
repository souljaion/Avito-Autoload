"""
Shared image processing: resize, convert to JPEG, strip metadata.
Supports HEIC/HEIF (iPhone photos) via pillow-heif.

CPU-heavy work (Pillow decode/resize/encode) runs in a threadpool executor
so the async event loop is not blocked.
"""

import asyncio
import time
from io import BytesIO

import structlog
from pillow_heif import register_heif_opener
from PIL import Image

register_heif_opener()
logger = structlog.get_logger(__name__)

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


def _sync_process_image(data: bytes, max_side: int = 1600, quality: int = 85) -> bytes:
    """Sync: resize image to max_side, convert to JPEG, strip metadata."""
    if len(data) > MAX_FILE_SIZE:
        raise ValueError(f"Файл слишком большой ({len(data) // 1024 // 1024} МБ, макс. {MAX_FILE_SIZE // 1024 // 1024} МБ)")

    t0 = time.monotonic()

    img = Image.open(BytesIO(data))

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    w, h = img.size
    if max(w, h) > max_side:
        if w >= h:
            new_w = max_side
            new_h = int(h * max_side / w)
        else:
            new_h = max_side
            new_w = int(w * max_side / h)
        img = img.resize((new_w, new_h), Image.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    result = buf.getvalue()

    elapsed = time.monotonic() - t0
    logger.info("image processed",
                input_kb=len(data) // 1024,
                output_kb=len(result) // 1024,
                size=f"{w}x{h}",
                elapsed=f"{elapsed:.2f}s")
    return result


def _sync_make_thumbnail(data: bytes, max_side: int = 300, quality: int = 70) -> bytes:
    """Sync: create a thumbnail from image bytes. Uses BILINEAR for speed."""
    img = Image.open(BytesIO(data))

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    w, h = img.size
    if max(w, h) > max_side:
        if w >= h:
            new_w = max_side
            new_h = int(h * max_side / w)
        else:
            new_h = max_side
            new_w = int(w * max_side / h)
        img = img.resize((new_w, new_h), Image.BILINEAR)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


# ── Sync wrappers (for direct calls in non-async contexts / tests) ──

def process_image(data: bytes, max_side: int = 1600, quality: int = 85) -> bytes:
    """Sync wrapper — use process_image_async in async code."""
    return _sync_process_image(data, max_side, quality)


def make_thumbnail(data: bytes, max_side: int = 300, quality: int = 70) -> bytes:
    """Sync wrapper — use make_thumbnail_async in async code."""
    return _sync_make_thumbnail(data, max_side, quality)


# ── Async wrappers (run CPU work in threadpool) ──

async def process_image_async(data: bytes, max_side: int = 1600, quality: int = 85) -> bytes:
    """Process image in threadpool executor to avoid blocking the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_process_image, data, max_side, quality)


async def make_thumbnail_async(data: bytes, max_side: int = 300, quality: int = 70) -> bytes:
    """Create thumbnail in threadpool executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_make_thumbnail, data, max_side, quality)
