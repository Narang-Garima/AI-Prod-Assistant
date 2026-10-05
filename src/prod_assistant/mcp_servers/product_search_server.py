from mcp.server.fastmcp import FastMCP #for hosting the MCP server

from prod_assistant.retriever.retrieval import Retriever
from ddgs import DDGS

import os
import re
from collections import defaultdict

# Initialize MCP server
MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "8001"))
mcp = FastMCP("hybrid_search", host=MCP_HOST, port=MCP_PORT)

# Initialize the credential-backed retriever only when the local-search tool is used.
# This keeps the MCP server (and its web-search tool) available when Astra credentials
# have not been configured yet.
retriever = None

RELEVANCY_THRESHOLD = float(os.getenv("MCP_RELEVANCY_THRESHOLD", "0.35"))
OVERLAP_THRESHOLD = float(os.getenv("MCP_OVERLAP_THRESHOLD", "0.15"))
STOPWORDS = {
    "the", "a", "an", "is", "are", "for", "to", "in", "on", "of", "and", "or",
    "with", "under", "best", "top", "buy", "price", "review", "reviews", "india",
}
PARENT_CATEGORY_KEYS = {
    "phone": {"iphone", "pixel", "galaxy", "phone", "mobile", "oneplus", "vivo", "oppo", "xiaomi", "redmi"},
    "laptop": {"laptop", "macbook", "notebook", "vivobook", "victus", "pavilion", "thinkpad"},
    "audio": {"airpods", "earbuds", "headset", "earphone", "tws", "buds"},
    "watch": {"watch", "smartwatch", "fit", "band", "wearable"},
    "gaming": {"playstation", "ps5", "xbox", "controller", "gaming"},
    "tv": {"tv", "oled", "smart tv"},
    "home": {"vacuum", "cleaner", "lamp", "air fryer", "home"},
    "kids art": {"kids", "art", "color", "crayon", "paint", "craft"},
    "beauty": {"sunscreen", "spf", "cream", "serum", "face wash", "moisturizer"},
}


def _get_retriever():
    global retriever
    if retriever is None:
        retriever = Retriever().load_retriever()
    return retriever


def _run_web_search(query: str) -> str:
    results = DDGS().text(query, max_results=5)
    blocks = []
    for item in results:
        title = (item.get("title") or "Untitled result").strip()
        url = (item.get("href") or item.get("url") or "").strip()
        body = (item.get("body") or "").strip()
        blocks.append(f"{title}\n{url}\n{body}".strip())
    return "\n\n".join(blocks) if blocks else "No web results found."


def _map_parent_from_source_query(raw_category: str) -> str:
    cat = (raw_category or "").strip().lower()
    for parent, keys in PARENT_CATEGORY_KEYS.items():
        if any(k in cat for k in keys):
            return parent
    return "other"

# ---------- Helpers ----------
def format_docs(docs) -> str:
    """Group retrieved review chunks by product for clearer attribution."""
    if not docs:
        return ""

    grouped = defaultdict(list)
    for d in docs:
        meta = d.metadata or {}
        product_id = str(meta.get("product_id", "N/A"))
        title = str(meta.get("product_title", "N/A"))
        category = str(meta.get("source_query", "N/A"))
        price = str(meta.get("price", "N/A"))
        rating = str(meta.get("rating", "N/A"))
        key = (product_id, title, category, price, rating)
        grouped[key].append((d.page_content or "").strip())

    blocks = []
    for (product_id, title, category, price, rating), reviews in grouped.items():
        unique_reviews = []
        seen = set()
        for r in reviews:
            norm = re.sub(r"\s+", " ", r).strip().lower()
            if not norm or norm in seen:
                continue
            seen.add(norm)
            unique_reviews.append(r)

        review_lines = []
        for idx, r in enumerate(unique_reviews[:3], start=1):
            review_lines.append(f"{idx}. {r}")

        blocks.append(
            f"Product ID: {product_id}\n"
            f"Title: {title}\n"
            f"Category: {category}\n"
            f"Price: {price}\n"
            f"Rating: {rating}\n"
            f"Matched Reviews:\n" + ("\n".join(review_lines) if review_lines else "No reviews found")
        )

    return "\n\n---\n\n".join(blocks)


def _tokenize(text: str) -> set[str]:
    base_tokens = set(re.findall(r"[a-zA-Z0-9]+", (text or "").lower()))
    expanded = set(base_tokens)

    # Normalize mixed tokens: "iphone17" -> "iphone", "17"
    for tok in list(base_tokens):
        parts = re.findall(r"[a-z]+|\d+", tok)
        if len(parts) > 1:
            expanded.update(parts)

    return {t for t in expanded if (len(t) > 2 or t.isdigit()) and t not in STOPWORDS}


def _overlap_ratio(query: str, context: str) -> float:
    q = _tokenize(query)
    if not q:
        return 0.0
    c = _tokenize(context)
    return len(q & c) / len(q)


def _extract_model_markers(text: str) -> set[str]:
    """
    Extract likely product model markers from a query/context.
    Examples:
    - "s26" -> "s26"
    - "iphone 17" -> "iphone17"
    - "pixel10" -> "pixel10"
    """
    raw = (text or "").lower()
    spaced = re.findall(r"\b[a-z]{1,15}\s+\d{1,3}\b", raw)
    compact = re.findall(r"\b[a-z]{1,15}\d{1,3}\b", raw)
    normalized = {re.sub(r"\s+", "", item) for item in spaced + compact}
    return {item for item in normalized if len(item) >= 3}


def _extract_category_hint(query: str) -> str:
    m = re.search(r"\[category:\s*([^\]]+)\]", (query or ""), flags=re.IGNORECASE)
    return (m.group(1).strip().lower() if m else "")


def _filter_blocks_by_category_hint(query: str, context: str) -> str:
    category = _extract_category_hint(query)
    if not category:
        return context
    blocks = [b for b in (context or "").split("\n\n---\n\n") if b.strip()]
    if not blocks:
        return context

    kept = []
    for block in blocks:
        m = re.search(r"^Category:\s*(.+)$", block, flags=re.IGNORECASE | re.MULTILINE)
        raw_cat = m.group(1).strip().lower() if m else ""
        parent = _map_parent_from_source_query(raw_cat)
        if category == parent or category == raw_cat:
            kept.append(block)
    return "\n\n---\n\n".join(kept)


def _filter_product_blocks_by_query(query: str, context: str) -> str:
    """
    Keep only the most query-relevant product blocks when retrieval returns mixed products.
    This helps follow-up queries like "price for it?" stay anchored to prior context.
    """
    blocks = [b for b in (context or "").split("\n\n---\n\n") if b.strip()]
    if len(blocks) <= 1:
        return context

    scored = [(block, _overlap_ratio(query, block)) for block in blocks]
    best = max(score for _, score in scored)
    if best <= 0:
        return context

    keep_threshold = max(0.08, best * 0.6)
    kept = [block for block, score in scored if score >= keep_threshold]
    if not kept:
        kept = [max(scored, key=lambda x: x[1])[0]]

    return "\n\n---\n\n".join(kept)

# ---------- MCP Tools ----------
@mcp.tool()
async def get_product_info(query: str) -> str:
    """Retrieve product information for a given query from local retriever."""
    try:
        docs = _get_retriever().invoke(query)
        context = format_docs(docs)
        if not context.strip():
            return "No local results found."

        context = _filter_blocks_by_category_hint(query, context)
        if not context.strip():
            return "No local results found."

        context = _filter_product_blocks_by_query(query, context)

        overlap = _overlap_ratio(query, context)
        if overlap < OVERLAP_THRESHOLD:
            return "No local results found."

        # Prevent silent substitution (e.g., user asks S26 and retriever returns S25).
        query_models = _extract_model_markers(query)
        if query_models:
            normalized_context = re.sub(r"\s+", "", context.lower())
            missing_models = [m for m in query_models if m not in normalized_context]
            if missing_models:
                return f"No local results found for exact model(s): {', '.join(missing_models)}."

        retrieved_contexts = [chunk for chunk in context.split("\n\n---\n\n") if chunk.strip()]
        # RAGAS uses external model calls and is intentionally loaded only after
        # deterministic product/category checks pass.
        from prod_assistant.evaluation.ragas_eval import evaluate_response_relevancy_async

        relevancy_score = await evaluate_response_relevancy_async(
            query=query,
            response=context,
            retrieved_context=retrieved_contexts,
        )

        if float(relevancy_score) < RELEVANCY_THRESHOLD:
            return "No local results found."

        return context
    except Exception as e:
        return f"Error retrieving product info: {str(e)}"

@mcp.tool()
async def web_search(query: str) -> str:
    """Search the web using DuckDuckGo if retriever has no results."""
    try:
        return _run_web_search(query)
    except Exception as e:
        return f"Error during web search: {str(e)}"

# ---------- Run Server ----------
if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "streamable-http").strip().lower()
    if transport == "streamable-http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
