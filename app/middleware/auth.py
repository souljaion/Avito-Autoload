import binascii
import secrets
from base64 import b64decode, b64encode

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
    # /media/ and /static/ — public assets (photos must be accessible by Avito)
    if path.startswith("/media/") or path.startswith("/static/"):
        return True
    return False


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.auth_b64 = ""
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
                request.state.auth_b64 = b64encode(f"{username}:{password}".encode()).decode()
                return await call_next(request)

        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Avito Autoload"'},
            content="Unauthorized",
        )
