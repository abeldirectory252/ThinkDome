"""Test fixtures."""

import os
import pytest
from httpx import AsyncClient, ASGITransport

# Force subprocess backend for tests (no Docker required)
os.environ["EXECUTOR_BACKEND"] = "subprocess"
os.environ["FILE_STORAGE_DIR"] = "/tmp/thinkbox-test-files"
# Tests must be hermetic and must not inherit a developer's .env PostgreSQL
# endpoint.  A local SQLite database also makes the suite deterministic when
# no external services are running.
os.environ["DATABASE_URL"] = "sqlite:////tmp/thinkbox-test.db"
os.environ["RABBITMQ_URL"] = ""

from thinkdome.api.server import create_app


@pytest.fixture
async def app():
    a = create_app()
    async with a.router.lifespan_context(a):
        yield a


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
