from typing import Annotated, Sequence, TypedDict, Literal
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

from prod_assistant.prompt_library.prompts import PROMPT_REGISTRY, PromptType
from prod_assistant.retriever.retrieval import Retriever
from prod_assistant.utils.model_loader import ModelLoader
from langgraph.checkpoint.memory import MemorySaver
import asyncio
import sys
from prod_assistant.evaluation.ragas_eval import evaluate_context_precision, evaluate_response_relevancy
from langchain_mcp_adapters.client import MultiServerMCPClient


class AgenticRAG:
    """Agentic RAG pipeline using LangGraph."""

    class AgentState(TypedDict):
        messages: Annotated[Sequence[BaseMessage], add_messages]
        rewrite_count: int

    def __init__(self):
        self.retriever_obj = Retriever()
        self.model_loader = ModelLoader()
        self.llm = self.model_loader.load_llm()
        self.checkpointer = MemorySaver()
        self.max_rewrites = 2
        
        # MCP Client Init
        self.mcp_client = MultiServerMCPClient({
            "product_retriever": {
                "command": sys.executable,
                "args": [r"C:\Users\KrishnaDasaNuDasi\AI-Prod-Assistant\src\prod_assistant\mcp_servers\product_search_server.py"],

               #"args": ["prod_assistant/mcp_servers/product_search_server.py"],  # absolute path recommended
                "transport": "stdio"
            }
        })
        # Load MCP tools (async ko sync wrapper me call karna hoga)
        self.mcp_tools = asyncio.run(self.mcp_client.get_tools())

        
        self.workflow = self._build_workflow()
        self.app = self.workflow.compile(checkpointer=self.checkpointer)

    # ---------- Helpers ----------
    def _latest_human_query(self, messages: Sequence[BaseMessage]) -> str:
        for m in reversed(messages):
            if isinstance(m, HumanMessage) and (m.content or "").strip():
                return m.content.strip()
        return (messages[-1].content or "").strip() if messages else ""

    def _format_docs(self, docs) -> str:
        if not docs:
            return "No relevant documents found."
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

    # ---------- Nodes ----------
    def _ai_assistant(self, state: AgentState):
        print("--- CALL ASSISTANT ---")
        last_message = self._latest_human_query(state["messages"])
        rewrite_count = int(state.get("rewrite_count", 0))

        # Keep rewritten queries in retrieval loop; avoid falling back to generic direct LLM answers.
        if rewrite_count > 0 or any(
            word in last_message.lower() for word in ["price", "review", "product"]
        ):
            return {"messages": [AIMessage(content="TOOL: retriever")]}
        else:
            prompt = ChatPromptTemplate.from_template(
                "You are a helpful assistant. Answer the user directly.\n\nQuestion: {question}\nAnswer:"
            )
            chain = prompt | self.llm | StrOutputParser()
            response = chain.invoke({"question": last_message})
            return {"messages": [AIMessage(content=response)]}

    def _vector_retriever(self, state: AgentState):
        print("--- RETRIEVER (MCP) ---")
        query = self._latest_human_query(state["messages"])
        # Find the tool by name
        tool = next(t for t in self.mcp_tools if t.name == "get_product_info")
        # Call the tool (sync wrapper)
        result = asyncio.run(tool.ainvoke({"query": query}))
        context = result if result else "No data"
        return {"messages": [AIMessage(content=context)]}

    def _grade_documents(self, state: AgentState) -> Literal["generator", "rewriter", "fallback"]:
        print("--- GRADER ---")
        question = self._latest_human_query(state["messages"])
        docs = state["messages"][-1].content
        rewrite_count = int(state.get("rewrite_count", 0))

        if rewrite_count >= self.max_rewrites:
            return "fallback"

        prompt = PromptTemplate(
            template="""You are a grader. Question: {question}\nDocs: {docs}\n
            Are docs relevant to the question? Answer yes or no.""",
            input_variables=["question", "docs"],
        )
        chain = prompt | self.llm | StrOutputParser()
        score = chain.invoke({"question": question, "docs": docs})
        return "generator" if "yes" in score.lower() else "rewriter"

    def _generate(self, state: AgentState):
        print("--- GENERATE ---")
        question = self._latest_human_query(state["messages"])
        docs = state["messages"][-1].content
        prompt = ChatPromptTemplate.from_template(
            PROMPT_REGISTRY[PromptType.PRODUCT_BOT].template
        )
        chain = prompt | self.llm | StrOutputParser()
        response = chain.invoke({"context": docs, "question": question})
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
        new_q = chain.invoke({"question": question})
        return {"rewrite_count": rc, "messages": [HumanMessage(content=new_q.strip())]}

    def _fallback(self, state: AgentState):
        print("--- FALLBACK ---")
        question = self._latest_human_query(state["messages"])
        return {
            "messages": [
                AIMessage(
                    content=f"I could not find reliable local results after {self.max_rewrites} rewrites. Try web search for: {question}"
                )
            ]
        }

    # ---------- Build Workflow ----------
    def _build_workflow(self):
        workflow = StateGraph(self.AgentState)
        workflow.add_node("Assistant", self._ai_assistant)
        workflow.add_node("Retriever", self._vector_retriever)
        workflow.add_node("Generator", self._generate)
        workflow.add_node("Rewriter", self._rewrite)
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
            {"generator": "Generator", "rewriter": "Rewriter", "fallback": "Fallback"},
        )
        workflow.add_edge("Generator", END)
        workflow.add_edge("Fallback", END)
        workflow.add_edge("Rewriter", "Assistant")
        return workflow

    # ---------- Public Run ----------
    def run(self, query: str,thread_id: str = "default_thread") -> str:
        """Run the workflow for a given query and return the final answer."""
        result = self.app.invoke(
            {"messages": [HumanMessage(content=query)], "rewrite_count": 0},
            config={"configurable": {"thread_id": thread_id}, "recursion_limit": 40},
        )
        return result["messages"][-1].content
    
if __name__ == "__main__":
    rag_agent = AgenticRAG()
    #answer = rag_agent.run("price for google pixel 10?")
    answer = rag_agent.run("Price for Asus laptop?")
    print("\nFinal Answer:\n", answer)
