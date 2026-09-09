# AI Production Assistant

An agentic product research assistant that answers product-related questions using local product data and web-search fallback.

The application uses LangGraph to control the workflow and MCP tools to retrieve product information. It first searches the Astra DB vector store. If the retrieved information is insufficient, it rewrites the query or uses web search before generating the final response.

## Features

- LangGraph-based agent workflow
- MCP tool integration
- Astra DB vector retrieval
- Product-information and web-search tools
- Context relevance checking
- Bounded query rewriting
- Conversation memory
- RAGAS evaluation
- FastAPI application and dashboard

## Request Flow

```text
User Question
      ↓
FastAPI
      ↓
LangGraph Workflow
      ↓
MCP Product Search
      ↓
Astra DB Retrieval
      ↓
Context Evaluation
   ┌──┴────────────┐
Relevant      Insufficient
   ↓                ↓
Answer       Rewrite / Web Search
   └────────┬───────┘
            ↓
      Final Response
```

## Technology Stack

- Python
- FastAPI
- LangGraph
- LangChain MCP Adapters
- Astra DB
- OpenAI, Google Gemini or Groq
- RAGAS
- SQLite
- Docker and Kubernetes

## Run Locally

```powershell
git clone https://github.com/Narang-Garima/AI-Prod-Assistant.git
cd AI-Prod-Assistant

python -m venv .venv
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

Create a `.env` file and provide the required service credentials:

```env
LLM_PROVIDER=openai

OPENAI_API_KEY=
GOOGLE_API_KEY=
GROQ_API_KEY=

ASTRA_DB_API_ENDPOINT=
ASTRA_DB_APPLICATION_TOKEN=
ASTRA_DB_KEYSPACE=
```

Start the MCP server:

```powershell
$env:MCP_TRANSPORT="streamable-http"
python src/prod_assistant/mcp_servers/product_search_server.py
```

Start the FastAPI application in another terminal:

```powershell
$env:PYTHONPATH="src"
$env:MCP_SERVER_URL="http://127.0.0.1:8001/mcp"
uvicorn prod_assistant.router.main:app --reload --port 8000
```

Open `http://127.0.0.1:8000`.

## Testing

```powershell
$env:PYTHONPATH="src"
pytest -q
```

## Security Note

The application uses environment variables for external service credentials. It does not currently implement end-user login or authorization.
