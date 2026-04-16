"""Shared rate limiter and JSON-friendly exception handler.

Uses slowapi with in-memory storage (per-process). Keyed by client IP.
For multi-worker deployments, consider Redis storage_uri.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address


# Module-level singleton — imported by main.py and decorated routes alike
limiter = Limiter(key_func=get_remote_address)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return JSON 429 with a clear message and the offending limit string."""
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate limit exceeded",
            "detail": f"Превышен лимит: {exc.detail}",
        },
        headers={"Retry-After": "60"},
    )
