"""
Shared image processing: resize, convert to JPEG, strip metadata.
"""

from io import BytesIO

from PIL import Image

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


def process_image(data: bytes, max_side: int = 1600, quality: int = 85) -> bytes:
    """Resize image to max_side, convert to JPEG, strip metadata. Returns JPEG bytes."""
    if len(data) > MAX_FILE_SIZE:
        raise ValueError(f"Файл слишком большой ({len(data) // 1024 // 1024} МБ, макс. {MAX_FILE_SIZE // 1024 // 1024} МБ)")

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
    return buf.getvalue()


def make_thumbnail(data: bytes, max_side: int = 300, quality: int = 70) -> bytes:
    """Create a thumbnail from JPEG bytes."""
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
    return buf.getvalue()
