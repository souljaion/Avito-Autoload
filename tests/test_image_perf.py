"""Performance benchmark: sequential vs parallel image processing."""

import asyncio
import time
from io import BytesIO

import pytest
import pillow_heif
from PIL import Image

from app.services.image_processor import (
    process_image,
    process_image_async,
    make_thumbnail,
    make_thumbnail_async,
)


def _make_large_heic(width=4032, height=3024) -> bytes:
    """Create a large HEIC image (~2.5MB, simulating iPhone photo)."""
    # Create a complex image with gradients to get realistic file size
    img = Image.new("RGB", (width, height))
    pixels = img.load()
    for y in range(height):
        for x in range(0, width, 4):  # every 4th pixel for speed
            r = (x * 255) // width
            g = (y * 255) // height
            b = ((x + y) * 128) // (width + height)
            for dx in range(min(4, width - x)):
                pixels[x + dx, y] = (r, g, b)
    heif_file = pillow_heif.from_pillow(img)
    buf = BytesIO()
    heif_file.save(buf, quality=90)
    return buf.getvalue()


def _make_large_jpeg(width=4032, height=3024) -> bytes:
    """Create a large JPEG for faster test generation."""
    img = Image.new("RGB", (width, height))
    pixels = img.load()
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            r = (x * 255) // width
            g = (y * 255) // height
            b = 128
            pixels[x, y] = (r, g, b)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_parallel_vs_sequential_performance():
    """Benchmark: process 6 images sequentially vs in parallel."""
    N = 6

    # Use JPEG for faster test image generation (HEIC creation is slow)
    print("\nGenerating test image...")
    t0 = time.monotonic()
    sample = _make_large_jpeg(3000, 2000)
    print(f"  Test image: {len(sample) // 1024}KB, generated in {time.monotonic() - t0:.1f}s")

    files = [sample] * N

    # Sequential
    t_seq_start = time.monotonic()
    for f in files:
        process_image(f, max_side=1600, quality=85)
    t_seq = time.monotonic() - t_seq_start

    # Parallel (threadpool)
    t_par_start = time.monotonic()
    await asyncio.gather(*[process_image_async(f, max_side=1600, quality=85) for f in files])
    t_par = time.monotonic() - t_par_start

    speedup = t_seq / t_par if t_par > 0 else 0

    print(f"\n{'='*50}")
    print(f"  Image Processing Benchmark ({N} files)")
    print(f"{'='*50}")
    print(f"  {'Method':<20} {'Time':>8} {'Per file':>10}")
    print(f"  {'-'*40}")
    print(f"  {'Sequential':<20} {t_seq:>7.2f}s {t_seq/N:>9.2f}s")
    print(f"  {'Parallel (gather)':<20} {t_par:>7.2f}s {t_par/N:>9.2f}s")
    print(f"  {'-'*40}")
    print(f"  Speedup: {speedup:.1f}x")
    print(f"{'='*50}\n")

    # Parallel should be faster (or at least not slower)
    assert t_par <= t_seq * 1.1, f"Parallel ({t_par:.2f}s) should not be slower than sequential ({t_seq:.2f}s)"
