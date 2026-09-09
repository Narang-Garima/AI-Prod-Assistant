import importlib
import sys
import types

from fastapi.testclient import TestClient


def _load_router_with_stubbed_agent():
    fake_workflow = types.ModuleType(
        "prod_assistant.workflow.agentic_workflow_with_mcp_websearch"
    )

    class FakeAgenticRAG:
        async def run(self, query: str, thread_id: str = "default_thread") -> str:
            return (
                f"echo:{query}\n\n"
                f"[MCP Tool Called: none]\n"
                f"[Route: direct]\n"
                f"[Thread: {thread_id}]"
            )

    fake_workflow.AgenticRAG = FakeAgenticRAG
    sys.modules["prod_assistant.workflow.agentic_workflow_with_mcp_websearch"] = (
        fake_workflow
    )
    sys.modules.pop("prod_assistant.router.main", None)
    return importlib.import_module("prod_assistant.router.main")


def test_index_route_returns_200_and_v1_is_not_exposed():
    router_main = _load_router_with_stubbed_agent()
    client = TestClient(router_main.app)
    assert client.get("/").status_code == 200
    assert client.get("/v1").status_code == 404


def test_health_endpoint():
    router_main = _load_router_with_stubbed_agent()
    client = TestClient(router_main.app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "shopbuddy-ai"}


def test_get_endpoint_sets_cookie_and_returns_agent_text():
    router_main = _load_router_with_stubbed_agent()
    client = TestClient(router_main.app)
    response = client.post("/get", data={"msg": "hello"})
    assert response.status_code == 200
    assert "echo:hello" in response.text
    assert "thread_id" in response.cookies
    assert "[Route: direct]" in response.text
