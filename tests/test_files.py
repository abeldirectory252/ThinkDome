"""File management endpoint tests."""

import pytest


@pytest.mark.asyncio
async def test_upload_and_download(client):
    # Upload
    resp = await client.post(
        "/v1/files/upload",
        files={"file": ("test.txt", b"hello content", "text/plain")},
    )
    assert resp.status_code == 200
    meta = resp.json()
    file_id = meta["file_id"]
    assert meta["filename"] == "test.txt"
    assert meta["size_bytes"] == len(b"hello content")

    # Download
    resp = await client.get(f"/v1/files/{file_id}")
    assert resp.status_code == 200
    assert resp.content == b"hello content"

    # Metadata
    resp = await client.get(f"/v1/files/{file_id}/metadata")
    assert resp.status_code == 200
    assert resp.json()["sha256"]

    # List
    resp = await client.get("/v1/files")
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1

    # Delete
    resp = await client.delete(f"/v1/files/{file_id}")
    assert resp.status_code == 200

    # Verify gone
    resp = await client.get(f"/v1/files/{file_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_copy_and_move(client):
    # Upload
    resp = await client.post(
        "/v1/files/upload",
        files={"file": ("orig.txt", b"data", "text/plain")},
    )
    file_id = resp.json()["file_id"]

    # Copy
    resp = await client.post(
        f"/v1/files/{file_id}/copy",
        json={"new_path": "copied.txt"},
    )
    assert resp.status_code == 200
    assert resp.json()["filename"] == "copied.txt"

    # Move
    resp = await client.post(
        f"/v1/files/{file_id}/move",
        json={"new_path": "moved.txt"},
    )
    assert resp.status_code == 200
    assert resp.json()["filename"] == "moved.txt"