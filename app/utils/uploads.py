"""Upload size validation utilities."""

from fastapi import HTTPException, Request

MAX_PHOTO_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB


def check_content_length(request: Request, max_bytes: int = MAX_PHOTO_UPLOAD_BYTES) -> int | None:
    """Reject requests early if Content-Length exceeds max_bytes.

    Returns the parsed content length, or None if the header is missing/invalid.
    Raises HTTPException(413) if the declared size is too large.
    """
    raw = request.headers.get("content-length")
    if raw is None:
        return None
    try:
        length = int(raw)
    except (ValueError, TypeError):
        return None
    if length > max_bytes:
        raise HTTPException(status_code=413, detail="File too large")
    return length
