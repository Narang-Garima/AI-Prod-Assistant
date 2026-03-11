FROM python:3.11-slim

WORKDIR /app

# install git
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# run MCP server + API in one container process command
CMD ["sh", "-c", "MCP_TRANSPORT=streamable-http MCP_HOST=127.0.0.1 MCP_PORT=8001 python src/prod_assistant/mcp_servers/product_search_server.py & MCP_SERVER_URL=http://127.0.0.1:8001/mcp uvicorn prod_assistant.router.main:app --host 0.0.0.0 --port 8000 --workers 2"]
