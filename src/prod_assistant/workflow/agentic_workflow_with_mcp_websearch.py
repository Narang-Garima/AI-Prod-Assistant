from typing import Annotated, Sequence, TypedDict, Literal
import asyncio

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

from prod_assistant.prompt_library.prompts import PROMPT_REGISTRY, PromptType
from prod_assistant.retriever.retrieval import Retriever
from prod_assistant.utils.model_loader import ModelLoader
from langchain_mcp_adapters.client import MultiServerMCPClient


class AgenticRAG:
    """Agentic RAG pipeline using LangGraph + MCP (Retriever + WebSearch)."""

    class AgentState(TypedDict):
        messages: Annotated[Sequence[BaseMessage], add_messages]
        rewrite_count: int
        last_mcp_tool: str

    def __init__(self):
        self.retriever_obj = Retriever()
        self.model_loader = ModelLoader()
        self.llm = self.model_loader.load_llm()
        self.checkpointer = MemorySaver()
        self.max_rewrites = 2

        self.mcp_client = MultiServerMCPClient(
            {
                "hybrid_search": {
                    "transport": "streamable_http",
                    "url": "http://localhost:8000/mcp",
                }
            }
        )

        self.workflow = self._build_workflow()
        self.app = self.workflow.compile(checkpointer=self.checkpointer)
        asyncio.run(self._safe_async_init())

    async def _safe_async_init(self):
        """Load MCP tools safely during construction."""
        try:
            self.mcp_tools = await self.mcp_client.get_tools()
            print("MCP tools loaded successfully.")
        except Exception as e:
            print(f"Warning: Failed to load MCP tools - {e}")
            self.mcp_tools = []

    def _latest_human_query(self, messages: Sequence[BaseMessage]) -> str:
        for m in reversed(messages):
            if isinstance(m, HumanMessage) and (m.content or "").strip():
                return m.content.strip()
        return (messages[-1].content or "").strip() if messages else ""

    def _ai_assistant(self, state: AgentState):
        print("--- CALL ASSISTANT ---")
        last_message = self._latest_human_query(state["messages"])
        rewrite_count = int(state.get("rewrite_count", 0))

        if rewrite_count > 0 or any(
            word in last_message.lower()
            for word in ["price", "review", "product", "iphone", "pixel", "samsung"]
        ):
            return {"messages": [AIMessage(content="TOOL: retriever")]}

        prompt = ChatPromptTemplate.from_template(
            "You are a helpful assistant. Answer the user directly.\n\nQuestion: {question}\nAnswer:"
        )
        chain = prompt | self.llm | StrOutputParser()
        response = chain.invoke({"question": last_message}) or "I'm not sure about that."
        return {"messages": [AIMessage(content=response)]}

    async def _vector_retriever(self, state: AgentState):
        print("--- RETRIEVER (MCP) ---")
        query = self._latest_human_query(state["messages"])

        tool = next((t for t in self.mcp_tools if t.name == "get_product_info"), None)
        if not tool:
            return {
                "last_mcp_tool": "get_product_info (not found)",
                "messages": [AIMessage(content="Retriever tool not found in MCP client.")],
            }

        try:
            result = await tool.ainvoke({"query": query})
            context = result or "No relevant product data found."
        except Exception as e:
            context = f"Error invoking retriever: {e}"

        return {"last_mcp_tool": "get_product_info", "messages": [AIMessage(content=context)]}

    async def _web_search(self, state: AgentState):
        print("--- WEB SEARCH (MCP) ---")
        query = self._latest_human_query(state["messages"])
        tool = next((t for t in self.mcp_tools if t.name == "web_search"), None)
        if not tool:
            return {
                "last_mcp_tool": "web_search (not found)",
                "messages": [AIMessage(content="Web search tool not found in MCP client.")],
            }

        try:
            result = await tool.ainvoke({"query": query})
            context = result if result else "No data from web"
        except Exception as e:
            context = f"Error invoking web search: {e}"

        return {"last_mcp_tool": "web_search", "messages": [AIMessage(content=context)]}

    def _grade_documents(self, state: AgentState) -> Literal["generator", "rewriter", "websearch", "fallback"]:
        print("--- GRADER ---")
        question = self._latest_human_query(state["messages"])
        docs = state["messages"][-1].content
        rewrite_count = int(state.get("rewrite_count", 0))

        if "No local results found." in (docs or ""):
            return "websearch"
        if rewrite_count >= self.max_rewrites:
            return "fallback"

        prompt = PromptTemplate(
            template=(
                "You are a grader. Question: {question}\nDocs: {docs}\n"
                "Are docs relevant to the question? Answer yes or no."
            ),
            input_variables=["question", "docs"],
        )
        chain = prompt | self.llm | StrOutputParser()
        score = chain.invoke({"question": question, "docs": docs}) or ""
        return "generator" if "yes" in score.lower() else "rewriter"

    def _generate(self, state: AgentState):
        print("--- GENERATE ---")
        question = self._latest_human_query(state["messages"])
        docs = state["messages"][-1].content

        prompt = ChatPromptTemplate.from_template(PROMPT_REGISTRY[PromptType.PRODUCT_BOT].template)
        chain = prompt | self.llm | StrOutputParser()

        try:
            response = chain.invoke({"context": docs, "question": question}) or "No response generated."
        except Exception as e:
            response = f"Error generating response: {e}"

        return {"messages": [AIMessage(content=response)]}

    def _rewrite(self, state: AgentState):
        print("--- REWRITE ---")
        question = self._latest_human_query(state["messages"])
        rc = int(state.get("rewrite_count", 0)) + 1

        prompt = ChatPromptTemplate.from_template(
            "Rewrite this user query to make it more clear and specific for a search engine. "
            "Do NOT answer the query. Only rewrite it.\n\nQuery: {question}\nRewritten Query:"
        )
        chain = prompt | self.llm | StrOutputParser()

        try:
            new_q = chain.invoke({"question": question}).strip()
        except Exception as e:
            new_q = f"Error rewriting query: {e}"

        return {"rewrite_count": rc, "messages": [HumanMessage(content=new_q)]}

    def _fallback(self, state: AgentState):
        print("--- FALLBACK ---")
        question = self._latest_human_query(state["messages"])
        return {
            "messages": [
                AIMessage(
                    content=(
                        f"I could not find reliable local results after {self.max_rewrites} rewrites. "
                        f"Try web search for: {question}"
                    )
                )
            ]
        }

    def _build_workflow(self):
        workflow = StateGraph(self.AgentState)
        workflow.add_node("Assistant", self._ai_assistant)
        workflow.add_node("Retriever", self._vector_retriever)
        workflow.add_node("Generator", self._generate)
        workflow.add_node("Rewriter", self._rewrite)
        workflow.add_node("WebSearch", self._web_search)
        workflow.add_node("Fallback", self._fallback)

        workflow.add_edge(START, "Assistant")
        workflow.add_conditional_edges(
            "Assistant",
            lambda state: "Retriever" if "TOOL" in state["messages"][-1].content else END,
            {"Retriever": "Retriever", END: END},
        )
        workflow.add_conditional_edges(
            "Retriever",
            self._grade_documents,
            {
                "generator": "Generator",
                "rewriter": "Rewriter",
                "websearch": "WebSearch",
                "fallback": "Fallback",
            },
        )
        workflow.add_edge("Rewriter", "Assistant")
        workflow.add_edge("WebSearch", "Generator")
        workflow.add_edge("Generator", END)
        workflow.add_edge("Fallback", END)

        return workflow

    async def run(self, query: str, thread_id: str = "default_thread") -> str:
        result = await self.app.ainvoke(
            {"messages": [HumanMessage(content=query)], "rewrite_count": 0, "last_mcp_tool": "none"},
            config={"configurable": {"thread_id": thread_id}, "recursion_limit": 40},
        )
        tool_name = result.get("last_mcp_tool", "none")
        return f'{result["messages"][-1].content}\n\n[MCP Tool Called: {tool_name}]'


if __name__ == "__main__":
    rag_agent = AgenticRAG()
    answer = asyncio.run(rag_agent.run("What is the reviews of asus vivobook laptop?"))
    print("\nFinal Answer:\n", answer)
