
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

rag_agent = AgenticRAG()

# ---------- FastAPI Endpoints ----------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})


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
    return answer

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000) 
