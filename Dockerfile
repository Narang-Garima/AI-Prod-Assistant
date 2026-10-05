FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir --index-url https://pypi.org/simple --retries 10 -r requirements.txt

COPY . .

EXPOSE 8000

# Portfolio/demo container: the MCP server and API share one container.
# A production design would run and scale them independently.
CMD ["sh", "-c", "MCP_TRANSPORT=streamable-http MCP_HOST=127.0.0.1 MCP_PORT=8001 python src/prod_assistant/mcp_servers/product_search_server.py & MCP_SERVER_URL=http://127.0.0.1:8001/mcp uvicorn prod_assistant.router.main:app --host 0.0.0.0 --port 8000 --workers 1"]
