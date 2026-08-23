"""Backwards-compatible ASGI entrypoints for the ThinkDome API server."""

from thinkdome.api.server import create_app, lifespan

# Some deployments import ``thinkdome.server:app`` directly, while the current
# CLI uses the factory form.  Keep the direct-ASGI entrypoint without forcing
# the factory module itself to create an application at import time.
app = create_app()


def start_server() -> None:
    """Run the API server using the configured host and port."""
    import uvicorn

    from thinkdome.core.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "thinkdome.api.server:create_app",
        factory=True,
        host=settings.HOST,
        port=settings.PORT,
        log_level="info",
    )
