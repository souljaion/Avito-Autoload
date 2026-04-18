"""
Subtle image uniquification for Avito.

Applies imperceptible random modifications so each copy
produces a unique file hash while looking identical to the human eye.
"""

import asyncio
import random
from io import BytesIO

import numpy as np
from PIL import Image, ImageEnhance


def uniquify_image(image_path: str, quality: int = 85) -> bytes:
    """Read an image, apply subtle random changes, return JPEG bytes."""
    img = Image.open(image_path).convert("RGB")
    img = _random_crop_resize(img)
    img = _random_brightness(img)
    img = _random_noise(img)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def uniquify_image_bytes(data: bytes, quality: int = 85) -> bytes:
    """Same as uniquify_image but accepts raw bytes instead of a file path."""
    img = Image.open(BytesIO(data)).convert("RGB")
    img = _random_crop_resize(img)
    img = _random_brightness(img)
    img = _random_noise(img)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


async def uniquify_image_async(image_path: str, quality: int = 85) -> bytes:
    """Async wrapper — runs uniquify_image in threadpool to avoid blocking the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, uniquify_image, image_path, quality)


async def uniquify_image_bytes_async(data: bytes, quality: int = 85) -> bytes:
    """Async wrapper — runs uniquify_image_bytes in threadpool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, uniquify_image_bytes, data, quality)


def _random_crop_resize(img: Image.Image) -> Image.Image:
    """Crop 1-3px from each side, then resize back to original dimensions."""
    w, h = img.size
    left = random.randint(1, 3)
    top = random.randint(1, 3)
    right = random.randint(1, 3)
    bottom = random.randint(1, 3)

    cropped = img.crop((left, top, w - right, h - bottom))
    return cropped.resize((w, h), Image.LANCZOS)


def _random_brightness(img: Image.Image) -> Image.Image:
    """Shift brightness by +/- 2-3%."""
    factor = 1.0 + random.uniform(-0.03, 0.03)
    return ImageEnhance.Brightness(img).enhance(factor)


def _random_noise(img: Image.Image) -> Image.Image:
    """Add very faint random noise (opacity 2-5%)."""
    arr = np.array(img, dtype=np.float32)
    opacity = random.uniform(0.02, 0.05)
    noise = np.random.uniform(-255, 255, arr.shape).astype(np.float32)
    arr = arr + noise * opacity
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)
