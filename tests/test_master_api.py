from __future__ import annotations

from mcp.master_api import MasterAPI


def test_master_api_register_and_mask():
    registry = MasterAPI()
    service = registry.register("", "ghp_1234567890abcdef")
    assert service == "github"
    assert registry.get("github") == "ghp_1234567890abcdef"
    masked = registry.masked("github")
    assert masked is not None
    assert masked.startswith("ghp_")
    assert masked.endswith("cdef")


def test_master_api_lists_services():
    registry = MasterAPI()
    registry.register("slack", "xoxb-abc")
    registry.register("notion", "secret_123")
    assert registry.list_services() == ["notion", "slack"]
