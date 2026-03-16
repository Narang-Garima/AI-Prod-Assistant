import os
import re
import sqlite3
from datetime import datetime, timezone
import uvicorn
from fastapi import FastAPI, Request, Form, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from prod_assistant.workflow.agentic_workflow_with_mcp_websearch import AgenticRAG
import uuid

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
DB_PATH = os.getenv("CHAT_HISTORY_DB", "data/chat_history.db")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

rag_agent = AgenticRAG()


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
    source, route = _parse_source_route(assistant_message)
    created_at = datetime.now(timezone.utc).isoformat()
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


@app.on_event("startup")
def startup() -> None:
    _ensure_db()


@app.get("/", response_class=HTMLResponse)
async def index_v1(request: Request):
    return templates.TemplateResponse("chat_v1.html", {"request": request})


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


@app.post("/get")
async def chat(
    request: Request,
    response: Response,
    msg: str = Form(...),
    thread_id: str | None = Form(default=None),
):
    if not thread_id:
        thread_id = request.cookies.get("thread_id")
    if not thread_id:
        thread_id = f"thread-{uuid.uuid4().hex}"
    response.set_cookie("thread_id", thread_id, httponly=False, samesite="lax")
    answer = await rag_agent.run(msg, thread_id=thread_id)
    if msg.strip():
        _save_turn(thread_id=thread_id, user_message=msg.strip(), assistant_message=answer)
    return answer

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
