def test_mcp_sse_routes_exist(app):
    paths = []
    for r in app.routes:
        path = getattr(r, "path", None)
        if path is not None:
            paths.append(path)
    assert "/mcp/sse" in paths
    assert "/mcp/messages" in paths
