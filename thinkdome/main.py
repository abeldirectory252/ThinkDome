"""thinkBox application entry point."""

import uvicorn
from thinkdome.core.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.app:create_app",
        factory=True,
        host=settings.HOST,
        port=settings.PORT,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
