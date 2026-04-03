import binascii
import secrets
from base64 import b64decode

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings

# Paths that skip authentication
_PUBLIC_PATHS = {"/health"}


def _is_public(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return True
    # /feeds/{account_id}.xml — public XML feed for Avito
    if path.startswith("/feeds/") and path.endswith(".xml"):
        return True
    return False


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if _is_public(request.url.path):
            return await call_next(request)

        # Static/media assets don't need auth check in browser context
        # (they are embedded in authenticated pages)

        auth = request.headers.get("Authorization")
        if auth and auth.startswith("Basic "):
            try:
                decoded = b64decode(auth[6:]).decode("utf-8")
                username, password = decoded.split(":", 1)
            except (binascii.Error, ValueError, UnicodeDecodeError):
                username, password = "", ""

            if (
                secrets.compare_digest(username, settings.BASIC_AUTH_USER)
                and secrets.compare_digest(password, settings.BASIC_AUTH_PASSWORD)
            ):
                return await call_next(request)

        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Avito Autoload"'},
            content="Unauthorized",
        )
