import asyncio
import importlib
import sys
import types
from types import SimpleNamespace


def _load_product_search_server_with_stubs():
    class DummyRetriever:
        def load_retriever(self):
            class _R:
                def invoke(self, query):
                    return []

            return _R()

    async def dummy_relevancy(*args, **kwargs):
        return 1.0

    class DummyMCP:
        def __init__(self, *args, **kwargs):
            pass

        def tool(self):
            def decorator(func):
                return func

            return decorator

        def run(self, *args, **kwargs):
            return None

    fake_retrieval = types.ModuleType("prod_assistant.retriever.retrieval")
    fake_retrieval.Retriever = DummyRetriever
    sys.modules["prod_assistant.retriever.retrieval"] = fake_retrieval

    fake_eval = types.ModuleType("prod_assistant.evaluation.ragas_eval")
    fake_eval.evaluate_response_relevancy_async = dummy_relevancy
    sys.modules["prod_assistant.evaluation.ragas_eval"] = fake_eval

    fake_fastmcp = types.ModuleType("mcp.server.fastmcp")
    fake_fastmcp.FastMCP = DummyMCP
    sys.modules["mcp.server.fastmcp"] = fake_fastmcp

    sys.modules.pop("prod_assistant.mcp_servers.product_search_server", None)
    return importlib.import_module("prod_assistant.mcp_servers.product_search_server")


def test_tokenize_splits_alnum_terms():
    mod = _load_product_search_server_with_stubs()
    tokens = mod._tokenize("price of iphone17 in india")
    assert "iphone17" in tokens
    assert "iphone" in tokens
    assert "17" in tokens


def test_overlap_ratio_detects_query_context_intersection():
    mod = _load_product_search_server_with_stubs()
    ratio = mod._overlap_ratio("google pixel 10 price", "Pixel 10 costs INR 52,999")
    assert ratio > 0


def test_format_docs_groups_and_dedupes_reviews():
    mod = _load_product_search_server_with_stubs()
    docs = [
        SimpleNamespace(
            page_content="Great camera and battery",
            metadata={"product_id": "P1", "product_title": "Phone A", "price": "100", "rating": "4.5"},
        ),
        SimpleNamespace(
            page_content="Great camera and battery",
            metadata={"product_id": "P1", "product_title": "Phone A", "price": "100", "rating": "4.5"},
        ),
    ]
    out = mod.format_docs(docs)
    assert "Product ID: P1" in out
    assert out.count("Great camera and battery") == 1


def test_get_product_info_returns_no_local_when_no_docs():
    mod = _load_product_search_server_with_stubs()
    mod.retriever = SimpleNamespace(invoke=lambda q: [])
    result = asyncio.run(mod.get_product_info("price of phone"))
    assert result == "No local results found."


def test_web_search_uses_duckduckgo_stub():
    mod = _load_product_search_server_with_stubs()
    mod._run_web_search = lambda query: f"web:{query}"
    result = asyncio.run(mod.web_search("asus vivobook reviews"))
    assert result == "web:asus vivobook reviews"


def test_filter_product_blocks_prefers_query_matching_product():
    mod = _load_product_search_server_with_stubs()
    context = (
        "Product ID: A1\nTitle: ARTIOS Watercolor Paper\nPrice: ₹390\nRating: 4.5\nMatched Reviews:\n1. Great for watercolor\n\n---\n\n"
        "Product ID: B2\nTitle: Apple iPhone 17\nPrice: ₹82,900\nRating: 4.6\nMatched Reviews:\n1. Fast performance"
    )
    query = "Previous query context: reviews for watercolor paper\nFollow-up query: price for it?"
    filtered = mod._filter_product_blocks_by_query(query, context)
    assert "ARTIOS Watercolor Paper" in filtered
    assert "Apple iPhone 17" not in filtered


def test_extract_category_hint_from_query_prefix():
    mod = _load_product_search_server_with_stubs()
    query = "[Category: sunscreen] suggest best options for oily skin"
    assert mod._extract_category_hint(query) == "sunscreen"


def test_filter_blocks_by_category_hint_keeps_matching_category_only():
    mod = _load_product_search_server_with_stubs()
    context = (
        "Product ID: A1\nTitle: Apple iPhone 15\nCategory: phone\nPrice: 50000\nRating: 4.6\nMatched Reviews:\n1. good\n\n---\n\n"
        "Product ID: B1\nTitle: UV Shield SPF 50\nCategory: sunscreen\nPrice: 499\nRating: 4.2\nMatched Reviews:\n1. nice"
    )
    query = "[Category: sunscreen] recommend product"
    filtered = mod._filter_blocks_by_category_hint(query, context)
    assert "UV Shield SPF 50" in filtered
    assert "Apple iPhone 15" not in filtered
