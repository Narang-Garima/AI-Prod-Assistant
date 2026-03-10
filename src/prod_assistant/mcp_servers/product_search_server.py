from mcp.server.fastmcp import FastMCP #for hosting the MCP server

from prod_assistant.retriever.retrieval import Retriever  
from langchain_community.tools import DuckDuckGoSearchRun

from prod_assistant.evaluation.ragas_eval import evaluate_response_relevancy_async
import os
import re

# Initialize MCP server
mcp = FastMCP("hybrid_search")

# Load retriever once
retriever_obj = Retriever()
retriever = retriever_obj.load_retriever()

# LangChain DuckDuckGo tool
duckduckgo = DuckDuckGoSearchRun()
RELEVANCY_THRESHOLD = float(os.getenv("MCP_RELEVANCY_THRESHOLD", "0.35"))
OVERLAP_THRESHOLD = float(os.getenv("MCP_OVERLAP_THRESHOLD", "0.15"))
STOPWORDS = {
    "the", "a", "an", "is", "are", "for", "to", "in", "on", "of", "and", "or",
    "with", "under", "best", "top", "buy", "price", "review", "reviews", "india",
}

# ---------- Helpers ----------
def format_docs(docs) -> str:
    """Format retriever docs into readable context."""
    if not docs:
        return ""
    formatted_chunks = []
    for d in docs:
        meta = d.metadata or {}
        formatted = (
            f"Title: {meta.get('product_title', 'N/A')}\n"
            f"Price: {meta.get('price', 'N/A')}\n"
            f"Rating: {meta.get('rating', 'N/A')}\n"
            f"Reviews:\n{d.page_content.strip()}"
        )
        formatted_chunks.append(formatted)
    return "\n\n---\n\n".join(formatted_chunks)


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

# ---------- MCP Tools ----------
@mcp.tool()
async def get_product_info(query: str) -> str:
    """Retrieve product information for a given query from local retriever."""
    try:
        docs = retriever.invoke(query)
        context = format_docs(docs)
        if not context.strip():
            return "No local results found."

        overlap = _overlap_ratio(query, context)
        if overlap < OVERLAP_THRESHOLD:
            return "No local results found."

        retrieved_contexts = [chunk for chunk in context.split("\n\n---\n\n") if chunk.strip()]
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
        return duckduckgo.run(query)
    except Exception as e:
        return f"Error during web search: {str(e)}"

# ---------- Run Server ----------
if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    if transport == "streamable-http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
