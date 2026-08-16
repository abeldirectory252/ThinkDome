"""Ensure HTTP responses have exactly one application-managed Date header.

Lightweight ASGI middleware (not BaseHTTPMiddleware) for minimal overhead.
Only adds a Date header when the application did not already provide one.
"""

from email.utils import formatdate

from starlette.types import ASGIApp, Message, Receive, Scope, Send

DATE_HEADER = b"date"


class DateHeaderMiddleware:
    """Add a current HTTP Date only when the application did not provide one."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_date(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                if not any(name.lower() == DATE_HEADER for name, _ in headers):
                    headers.append((DATE_HEADER, formatdate(usegmt=True).encode("ascii")))
                    message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_date)
