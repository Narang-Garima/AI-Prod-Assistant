import os
import re
import sqlite3
import csv
import json
from contextlib import asynccontextmanager
from collections import defaultdict
from datetime import datetime, timezone
import uvicorn
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, Response, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from prod_assistant.workflow.agentic_workflow_with_mcp_websearch import AgenticRAG
import uuid


load_dotenv(Path(__file__).resolve().parents[3] / ".env")


@asynccontextmanager
async def lifespan(_: FastAPI):
    _ensure_db()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
DB_PATH = os.getenv("CHAT_HISTORY_DB", "data/chat_history.db")
REVIEWS_HISTORY_CSV = os.getenv("REVIEWS_HISTORY_CSV", "data/product_reviews_history.csv")
POSTER_DIR = os.getenv("POSTER_DIR", "poster")

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://127.0.0.1:8000,http://localhost:8000",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

rag_agent: AgenticRAG | None = None


def _get_rag_agent() -> AgenticRAG:
    global rag_agent
    if rag_agent is None:
        rag_agent = AgenticRAG()
    return rag_agent

_CATEGORY_RULES = [
    ("phone", {"iphone", "pixel", "galaxy", "phone", "mobile", "oneplus", "vivo", "oppo", "xiaomi", "redmi"}),
    ("laptop", {"laptop", "macbook", "notebook", "vivobook", "victus", "pavilion", "thinkpad"}),
    ("audio", {"airpods", "earbuds", "headset", "earphone", "tws", "buds"}),
    ("watch", {"watch", "smartwatch", "fit", "band", "wearable"}),
    ("gaming", {"playstation", "ps5", "xbox", "controller", "gaming"}),
    ("tv", {"tv", "oled", "smart tv"}),
    ("home", {"vacuum", "cleaner", "lamp", "air fryer", "home"}),
    ("kids art", {"kids", "art", "color", "crayon", "paint", "craft"}),
    ("beauty", {"sunscreen", "spf", "cream", "serum", "face wash", "moisturizer"}),
]


def _ensure_db() -> None:
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                user_message TEXT NOT NULL,
                assistant_message TEXT NOT NULL,
                source TEXT NOT NULL,
                route TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            )
            """
        )
        conn.commit()


def _parse_source_route(assistant_text: str) -> tuple[str, str]:
    source = "none"
    route = "none"
    source_match = re.search(r"\[MCP Tool Called:\s*([^\]]+)\]", assistant_text or "", flags=re.IGNORECASE)
    route_match = re.search(r"\[Route:\s*([^\]]+)\]", assistant_text or "", flags=re.IGNORECASE)
    if source_match:
        source = source_match.group(1).strip()
    if route_match:
        route = route_match.group(1).strip()
    return source, route


def _save_turn(thread_id: str, user_message: str, assistant_message: str) -> None:
    # Make history persistence best-effort so chat responses never fail if DB is unavailable.
    try:
        _ensure_db()
    except Exception:
        return

    source, route = _parse_source_route(assistant_message)
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO chat_turns
                (thread_id, user_message, assistant_message, source, route, created_at_utc)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (thread_id, user_message, assistant_message, source, route, created_at),
            )
            conn.commit()
    except Exception:
        return


def _safe_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() == "N/A":
        return None
    cleaned = re.sub(r"[^0-9.]", "", text)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _map_to_parent_category(source_query: str, product_title: str) -> str:
    sq = _normalize_text(source_query)
    pt = _normalize_text(product_title)

    # Primary signal: user/source query phrase.
    text = sq if sq else pt
    for category, keys in _CATEGORY_RULES:
        for k in keys:
            if k in text:
                return category
    return "other"


def _load_categories() -> list[dict]:
    if not os.path.exists(REVIEWS_HISTORY_CSV):
        return []

    counts: dict[str, int] = defaultdict(int)
    with open(REVIEWS_HISTORY_CSV, "r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            category = _map_to_parent_category(
                row.get("source_query") or "",
                row.get("product_title") or "",
            )
            if category:
                counts[category] += 1

    return [
        {"value": c, "label": c.title(), "count": n}
        for c, n in sorted(counts.items(), key=lambda x: x[1], reverse=True)
    ]


def _build_dashboard_payload(category_filter: str) -> dict:
    if not os.path.exists(REVIEWS_HISTORY_CSV):
        return {
            "error": f"CSV not found at: {REVIEWS_HISTORY_CSV}",
            "category_counts": {},
            "avg_rating_by_category": {},
            "avg_price_by_category": {},
            "trend_by_date": {},
        }

    aggregate_counts: dict[str, int] = defaultdict(int)
    rating_sum: dict[str, float] = defaultdict(float)
    rating_n: dict[str, int] = defaultdict(int)
    price_sum: dict[str, float] = defaultdict(float)
    price_n: dict[str, int] = defaultdict(int)
    trend_by_date: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    compare_option_counts: dict[str, int] = defaultdict(int)

    with open(REVIEWS_HISTORY_CSV, "r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            source_query = _normalize_text(row.get("source_query") or "")
            product_title = _normalize_text(row.get("product_title") or "")
            parent_category = _map_to_parent_category(source_query, product_title)
            if not parent_category:
                continue

            if category_filter and category_filter != "all" and parent_category != category_filter:
                continue

            ts = (row.get("scrape_timestamp_utc") or "").strip()
            date_key = ts[:10] if len(ts) >= 10 else "unknown"
            rating = _safe_float(row.get("rating"))
            price = _safe_float(row.get("price"))

            # all => aggregate by parent category; selected => aggregate by source query (iphone, pixel, etc.)
            aggregate_key = parent_category if category_filter == "all" else (source_query or product_title or "unknown")

            aggregate_counts[aggregate_key] += 1
            trend_by_date[date_key][aggregate_key] += 1
            compare_option_counts[aggregate_key] += 1

            if rating is not None:
                rating_sum[aggregate_key] += rating
                rating_n[aggregate_key] += 1
            if price is not None:
                price_sum[aggregate_key] += price
                price_n[aggregate_key] += 1

    avg_rating_by_category = {
        c: round(rating_sum[c] / rating_n[c], 2) for c in rating_n if rating_n[c] > 0
    }
    avg_price_by_category = {
        c: round(price_sum[c] / price_n[c], 2) for c in price_n if price_n[c] > 0
    }

    return {
        "error": None,
        "category_counts": dict(sorted(aggregate_counts.items(), key=lambda x: x[1], reverse=True)[:12]),
        "avg_rating_by_category": dict(sorted(avg_rating_by_category.items(), key=lambda x: x[1], reverse=True)[:12]),
        "avg_price_by_category": dict(sorted(avg_price_by_category.items(), key=lambda x: x[1])[:12]),
        "trend_by_date": {k: dict(v) for k, v in sorted(trend_by_date.items(), key=lambda x: x[0])},
        "compare_options": [
            {"value": k, "label": k.title(), "count": v}
            for k, v in sorted(compare_option_counts.items(), key=lambda x: x[1], reverse=True)
        ],
    }


def _resolve_poster_dir() -> Path:
    return Path(POSTER_DIR).resolve()


@app.get("/", response_class=HTMLResponse)
async def index_v1(request: Request):
    return templates.TemplateResponse(request, "chat_v1.html")


@app.get("/health")
def health():
    required_retrieval_settings = [
        "GOOGLE_API_KEY",
        "ASTRA_DB_API_ENDPOINT",
        "ASTRA_DB_APPLICATION_TOKEN",
        "ASTRA_DB_KEYSPACE",
    ]
    provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    provider_key = {
        "openai": "OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY",
        "groq": "GROQ_API_KEY",
    }.get(provider)

    return {
        "status": "ok",
        "application": "shopbuddy",
        "llm_provider": provider,
        "llm_configured": bool(provider_key and os.getenv(provider_key)),
        "local_retrieval_configured": all(os.getenv(name) for name in required_retrieval_settings),
        "mcp_server_url": os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8001/mcp"),
    }


@app.get("/_categories")
def get_categories():
    return {"categories": _load_categories()}


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, category: str = "all"):
    category_filter = (category or "all").strip().lower()
    payload = _build_dashboard_payload(category_filter)
    categories = _load_categories()

    trend = payload["trend_by_date"]
    dates = list(trend.keys())
    series_categories = sorted({c for d in trend.values() for c in d.keys()})
    trend_datasets = [
        {
            "label": cat,
            "data": [trend.get(day, {}).get(cat, 0) for day in dates],
        }
        for cat in series_categories
    ]

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "selected_category": category_filter,
            "categories_json": json.dumps(categories),
            "compare_options_json": json.dumps(payload["compare_options"]),
            "error": payload["error"],
            "count_labels_json": json.dumps(list(payload["category_counts"].keys())),
            "count_values_json": json.dumps(list(payload["category_counts"].values())),
            "rating_labels_json": json.dumps(list(payload["avg_rating_by_category"].keys())),
            "rating_values_json": json.dumps(list(payload["avg_rating_by_category"].values())),
            "price_labels_json": json.dumps(list(payload["avg_price_by_category"].keys())),
            "price_values_json": json.dumps(list(payload["avg_price_by_category"].values())),
            "count_map_json": json.dumps(payload["category_counts"]),
            "rating_map_json": json.dumps(payload["avg_rating_by_category"]),
            "price_map_json": json.dumps(payload["avg_price_by_category"]),
            "trend_labels_json": json.dumps(dates),
            "trend_datasets_json": json.dumps(trend_datasets),
        },
    )


@app.get("/_history/threads")
def list_threads():
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT thread_id, COUNT(*) AS turns, MAX(created_at_utc) AS last_seen
            FROM chat_turns
            GROUP BY thread_id
            ORDER BY last_seen DESC
            """
        ).fetchall()
    return [{"thread_id": r[0], "turns": r[1], "last_seen": r[2]} for r in rows]


@app.get("/_history/{thread_id}")
def get_thread_history(thread_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT id, thread_id, user_message, assistant_message, source, route, created_at_utc
            FROM chat_turns
            WHERE thread_id = ?
            ORDER BY id ASC
            """,
            (thread_id,),
        ).fetchall()
    return [
        {
            "id": r[0],
            "thread_id": r[1],
            "user_message": r[2],
            "assistant_message": r[3],
            "source": r[4],
            "route": r[5],
            "created_at_utc": r[6],
        }
        for r in rows
    ]


@app.get("/_posters")
def list_posters():
    poster_dir = _resolve_poster_dir()
    if not poster_dir.exists() or not poster_dir.is_dir():
        return {"files": []}

    files = sorted(
        [p.name for p in poster_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"],
        key=str.lower,
    )
    return {"files": files}


@app.get("/download/poster/{filename}")
def download_poster(filename: str):
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed.")

    poster_dir = _resolve_poster_dir()
    if not poster_dir.exists() or not poster_dir.is_dir():
        raise HTTPException(status_code=404, detail="Poster directory not found.")

    target = (poster_dir / filename).resolve()
    if target.parent != poster_dir:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="PDF not found.")

    return FileResponse(path=str(target), filename=target.name, media_type="application/pdf")


@app.post("/get")
async def chat(
    request: Request,
    response: Response,
    msg: str = Form(...),
    thread_id: str | None = Form(default=None),
    category_hint: str | None = Form(default=None),
):
    if not thread_id:
        thread_id = request.cookies.get("thread_id")
    if not thread_id:
        thread_id = f"thread-{uuid.uuid4().hex}"
    response.set_cookie(
        "thread_id",
        thread_id,
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "false").strip().lower() == "true",
        samesite="lax",
    )

    user_msg = (msg or "").strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    category = (category_hint or "auto").strip().lower()
    effective_query = user_msg if category == "auto" else f"[Category: {category}] {user_msg}"

    try:
        answer = await _get_rag_agent().run(effective_query, thread_id=thread_id)
    except (EnvironmentError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Assistant dependencies are not configured: {exc}",
        ) from exc
    if answer.startswith("Error generating response:"):
        raise HTTPException(status_code=502, detail=answer.split("\n", 1)[0])
    if user_msg:
        _save_turn(thread_id=thread_id, user_message=user_msg, assistant_message=answer)
    return answer

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
