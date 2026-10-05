# Implementation and validation notes

I use this document to record how I validated ShopBuddy locally, the issues I found, and the fixes I made. This keeps my portfolio claims traceable to actual code and run results.

## What I started with

The repository was clean at commit `312fa85` on the `master` branch before I began this improvement pass.

The existing implementation already included:

- Flipkart product-review acquisition using Selenium, undetected-chromedriver, and BeautifulSoup
- pandas-based CSV cleanup, schema validation, and review splitting
- Google embeddings and Astra DB vector storage
- a LangGraph workflow with direct, memory, retrieval, grading, rewrite, web-search, generation, and fallback routes
- MCP tools for local product retrieval and web search
- a FastAPI chat interface, analytics dashboard, poster download, and SQLite chat history
- a Streamlit interface for scraping and ingestion
- inline RAGAS response-relevancy evaluation

I did not find implemented fine-tuning, LoRA/PEFT, production monitoring, distributed tracing, a durable LangGraph checkpointer, end-user authentication, or a verified cloud deployment. I therefore do not claim these features.

## Initial validation

I ran the following baseline checks on Windows with Python 3.11.6:

```text
git status --short --branch
Result: clean; master...origin/master

python -m pytest -q test
Result: 22 passed, 6 warnings in 76.63 seconds

python -m compileall -q -f src scrape_buddy.py scrape_buddy_powerbi.py
Result: exit code 0

python main.py
Result: printed the original placeholder message
```

The first FastAPI and MCP imports exposed tight import-time coupling to Google and Astra configuration. I also found a personal absolute Windows path in the MCP client. I did not find a tracked `.env`, embedded application token, or private key.

## Improvements I made

### Repository and configuration

- I replaced broad ignore rules that excluded all Markdown and the entire `docs/` directory.
- I added a safe `.env.example` and `.dockerignore` without credential values.
- I consolidated direct runtime dependencies in `pyproject.toml` and kept `requirements.txt` as an editable project install.
- I removed generated data, reports, logs, caches, local databases, and credentials from the versioned project scope.
- I removed the hard-coded Windows username path from the MCP client.

### RAG, MCP, and API behavior

- I removed unnecessary eager retriever construction from the graph workflow.
- I made MCP discovery and Astra retriever creation lazy so the server can start without immediately contacting every dependency.
- I replaced an incompatible DuckDuckGo wrapper with the declared `ddgs` implementation.
- I moved rewrite and recursion limits into configuration.
- I added a secret-safe `/health` endpoint, configurable CORS, HttpOnly thread cookies, empty-message validation, and sanitized provider failures.
- I made the FastAPI application load `.env` before reporting configuration health.
- I replaced the placeholder `main.py` behavior with the FastAPI launcher.

### Portfolio accuracy

- I rewrote the README around the implemented acquisition-to-application workflow.
- I added a code-backed Mermaid architecture diagram and a screenshot captured from the real local interface.
- I removed older diagrams that showed unimplemented fine-tuning, guardrails, Bedrock, Redis, DynamoDB, and similar services.
- I retained Docker, Kubernetes, EKS, and GitHub Actions as optional infrastructure definitions, not as proof of deployment.
- I removed a duplicate poster and a hard-coded ECR account identifier.

### Evaluation and Windows fixes

- I added a five-case retrieval evaluation dataset and a credential-backed RAGAS runner.
- I changed RAGAS response relevancy to one generated candidate because the current Gemini model rejects multi-candidate requests.
- I made the evaluation runner record metric errors independently and pace provider requests.
- I replaced the unavailable `gemini-2.5-flash` configuration with `gemini-3.8-flash` after verifying the provider's 404 response.
- I removed emoji from scraper console messages after they caused a CP1252 `UnicodeEncodeError` on Windows.
- I removed the hard-coded Chrome major version and kept auto-detection with an optional override.

## Live workflow validation

### Data acquisition

I first ran a one-product headless scrape for `wireless mouse`. It returned one row with all six expected columns and usable review text.

I then ran the sequential scraper for `wireless mouse`, `sunscreen sensitive skin`, and `budget laptop`, using one product per query and requesting two reviews per product.

```text
Product rows: 3
Expected columns present: 6/6
Non-empty titles: 3
Rating values present: 3
Price values present: 3
Duplicate product IDs: 0
Review segments by row: 2, 2, and 1 short placeholder
```

The first multi-product attempt stopped before Chrome opened because Windows could not print an emoji status message. After changing the messages to plain text, the scrape completed with exit code 0.

`undetected-chromedriver` emitted ignored `WinError 6` destructor warnings after the completed runs. I recorded these as cleanup warnings because the CSV had already been written successfully.

### Embeddings, Astra DB, and ingestion

I checked credential presence without printing secret values. The local `.env` remains ignored by Git.

```text
Astra authentication: successful
Initial Astra collection count: 0
Google embedding request: successful
Embedding dimension: 3072
gemini-2.5-flash request: HTTP 404, unavailable to new users
gemini-3.8-flash request: successful
```

I transformed the three scraped product rows into five LangChain review documents. The ingestion pipeline created the `ecommercedata` collection and confirmed insertion of all five documents.

The process exited 0. At interpreter shutdown, gRPC emitted an ignored `AioChannel` cleanup traceback after the confirmed write.

For the evaluation expansion, I scraped 14 more raw product rows across laptop, phone, headphones, smartwatch, skincare, power-bank, earbuds, and keyboard searches. I excluded six short no-review placeholders and removed a duplicate product ID. The resulting curated local dataset contains 10 products and 17 usable review documents.

I inserted only the 13 new documents into Astra, avoiding reinsertion of the original evidence. The Astra collection therefore contains 18 stored documents in total: the original five, including one placeholder later removed by retrieval cleanup, plus the 13 new documents.

### Retrieval quality

I ran all five benchmark questions directly against the stored Astra vectors.

```text
Raw documents per query: 5
Cleaned contexts per query: 4
Products represented in cleaned results: 2
```

The useful contexts represented the sunscreen and wireless mouse. The laptop row contained only a short no-review placeholder, which the retriever excluded from cleaned results.

The negative-control question also returned four contexts. This is an important limitation: the current retriever always returns nearest neighbors and does not yet apply a similarity threshold or explicit no-evidence gate.

### FastAPI and MCP

I verified the MCP server and FastAPI application locally. The MCP client negotiated protocol version `2025-06-18`, discovered both tools, and successfully invoked the live web-search fallback.

Before fresh Google/Astra configuration was available, the old OpenAI credential returned HTTP 401. The application converted that provider failure into a sanitized HTTP 502 instead of exposing the raw response.

After configuring Google and Astra, I repeated the application checks:

```text
GET /health: 200
LLM provider: google
LLM configured: true
Local retrieval configured: true

POST /get with msg=hi: 200
Route: direct
MCP tool: none
HttpOnly thread cookie: present
```

I also verified one real Google chat completion before reaching the daily model quota.

After expanding the corpus and selecting the verified Flash Lite model, I ran a real product question through the complete application path:

```text
FastAPI status: 200
MCP protocol: 2025-06-18
MCP tool: get_product_info
Saved workflow route: retriever
Answer length: 801 characters
Generation error: false
```

This check exercised FastAPI, LangGraph, MCP discovery and invocation, Astra retrieval, the inline RAGAS gate, and Gemini answer generation in one request.

## Evaluation outcome

The first RAGAS attempt exposed a Gemini incompatibility with multiple generated candidates. I fixed this by setting response-relevancy strictness to one. The original Flash-model quota was then exhausted, so I queried the provider's live model list and verified `gemini-3.5-flash-lite` with a minimal request before using its separate available quota.

The paced rerun completed all five cases and both metrics:

```text
Context precision scored cases: 5/5
Mean context precision without reference: 0.4333
Response relevancy scored cases: 5/5
Mean response relevancy: 0.8000
Metric errors: 0
```

The score is a baseline rather than a quality claim. The sunscreen case scored 0 on both metrics, and the negative control received high response relevancy despite retrieving unrelated nearest-neighbor contexts. I documented every case in `docs/evaluation.md`.

## Final checks

```text
python -m compileall -q -f src main.py scrape_buddy.py scrape_buddy_powerbi.py
Result: exit code 0

python -m pytest -q
Result: 28 passed, 1 third-party LangGraph warning in 24.38 seconds

python -m pip install --dry-run --no-deps -e .
Result: editable package metadata built successfully

YAML parsing
Result: 6 application, workflow, Kubernetes, and configuration files parsed

git diff --check
Result: no whitespace errors; Windows line-ending notices only

Secret-pattern scan
Result: 0 findings outside ignored runtime directories
```

## Scope

I present ShopBuddy as a local applied-GenAI product assistant that connects acquisition, preprocessing, vector retrieval, agent routing, MCP tools, API/UI delivery, and evaluation.

I do not present it as a production deployment, enterprise-scale system, fine-tuned model, monitored LLMOps platform, or proven cloud workload. Docker, Kubernetes, EKS, and deployment workflows are optional next steps that still require separate infrastructure validation.
