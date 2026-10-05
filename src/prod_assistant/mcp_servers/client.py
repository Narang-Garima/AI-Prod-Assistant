import asyncio
from pathlib import Path
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
import sys

async def main():
    server_script = Path(__file__).resolve().with_name("product_search_server.py")
    client = MultiServerMCPClient({
        "hybrid_search": {   # server name
            "command": sys.executable,
            "args": [str(server_script)],
            "transport": "stdio",
        }
    })

    async with client.session("hybrid_search") as session:
        # Discover tools
        tools = await load_mcp_tools(session)
        print("Available tools:", [t.name for t in tools])

        # Pick tools by name
        retriever_tool = next(t for t in tools if t.name == "get_product_info")
        web_tool = next(t for t in tools if t.name == "web_search")

        # --- Step 1: Try retriever first ---
        #query = "Samsung Galaxy S25 price"
        query = "best phone with respect to value for money among  google pixel 10 and iphone 17?"
        #query = "best budget gaming laptop under 70000 in india 2026?"
        retriever_result = await retriever_tool.ainvoke({"query": query})
        print("\nRetriever Result:\n", retriever_result)

        # --- Step 2: Fallback to web search if retriever fails ---
        if not retriever_result.strip() or "No local results found." in retriever_result:
            print("\n No local results, falling back to web search...\n")
            web_result = await web_tool.ainvoke({"query": query})
            print("Web Search Result:\n", web_result)

if __name__ == "__main__":
    asyncio.run(main())
