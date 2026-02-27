"""Tests for the MCP server health check endpoint."""

from __future__ import annotations


def test_health_endpoint_returns_200():
    """Health check should return 200 OK with status info."""
    from starlette.testclient import TestClient

    from crucis.mcp.server import mcp as server

    app = server.streamable_http_app()
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["server"] == "crucis-mcp"
