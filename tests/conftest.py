"""Test fixtures."""

import os
import pytest
from httpx import AsyncClient, ASGITransport

# Force subprocess backend for tests (no Docker required)
os.environ["EXECUTOR_BACKEND"] = "subprocess"
os.environ["FILE_STORAGE_DIR"] = "/tmp/thinkbox-test-files"

from thinkdome.server import create_app


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