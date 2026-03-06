# agentic_rag_workflow.py
# NOTE: This version reads agent settings from config.yaml (agentic_rag section)
# and prevents infinite loops (max rewrites + fallback).



# ---------- imports ----------
from typing import Annotated, Sequence, TypedDict, Literal, Optional

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.output_parsers import StrOutputParser

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

from prod_assistant.utils.config_loader import load_config
from prod_assistant.prompt_library.prompts import PROMPT_REGISTRY, PromptType
from prod_assistant.retriever.retrieval import Retriever
from prod_assistant.utils.model_loader import ModelLoader


class AgenticRAG:
    """Agentic RAG pipeline using LangGraph with config.yaml controls."""

    class AgentState(TypedDict):
        messages: Annotated[Sequence[BaseMessage], add_messages]
        rewrite_count: int

    def __init__(self):
        self.config = load_config()

        # ----- Configurable knobs from config.yaml -----
        agent_cfg = self.config.get("agentic_rag", {}) if isinstance(self.config, dict) else {}

        self.max_rewrites: int = int(agent_cfg.get("max_rewrites", 2))
        self.recursion_limit: int = int(agent_cfg.get("recursion_limit", 60))
        self.fallback_enabled: bool = bool(agent_cfg.get("fallback_enabled", True))

        # keywords used to decide if we should call retriever
        self.routing_keywords = agent_cfg.get(
            "routing_keywords",
            ["price", "review", "rating", "product", "recommend", "suggest"],
        )

        # grader prompt (optional override)
        self.grader_prompt: str = agent_cfg.get(
            "grader_prompt",
            (
                "You are a grader.\n"
                "Question: {question}\n"
                "Docs: {docs}\n\n"
                "Are the docs relevant to answer the question? Answer only yes or no."
            ),
        )

        # direct answer prompt (optional override)
        self.direct_answer_prompt: str = agent_cfg.get(
            "direct_answer_prompt",
            "You are a helpful assistant. Answer the user directly.\n\nQuestion: {question}\nAnswer:",
        )

        # fallback message (optional override)
        self.fallback_message: str = agent_cfg.get(
            "fallback_message",
            (
                "I couldn’t find reliable information in the product review database to answer that.\n"
                "Try asking with a different model name or share a product link."
            ),
        )

        # ----- core components -----
        self.retriever_obj = Retriever()
        self.model_loader = ModelLoader()
        self.llm = self.model_loader.load_llm()

        self.checkpointer = MemorySaver()
        self.workflow = self._build_workflow()
        self.app = self.workflow.compile(checkpointer=self.checkpointer)

    # ---------- Helpers ----------
    def _latest_human_query(self, messages: Sequence[BaseMessage]) -> str:
        for m in reversed(messages):
            if isinstance(m, HumanMessage) and (m.content or "").strip():
                return m.content.strip()
        # fallback to very first message
        return (messages[0].content or "").strip() if messages else ""

    def _format_docs(self, docs) -> str:
        if not docs:
            return "No relevant documents found."

        formatted_chunks = []
        for d in docs:
            # safety if some retrievers return (Document, score)
            if isinstance(d, tuple):
                d = d[0]

            meta = getattr(d, "metadata", {}) or {}
            text = getattr(d, "page_content", "") or ""

            formatted_chunks.append(
                f"Title: {meta.get('product_title', 'N/A')}\n"
                f"Price: {meta.get('price', 'N/A')}\n"
                f"Rating: {meta.get('rating', 'N/A')}\n"
                f"Review:\n{text.strip()}"
            )

        return "\n\n---\n\n".join(formatted_chunks)

    # ---------- Nodes ----------
    def _assistant(self, state: AgentState):
        print("--- CALL ASSISTANT ---")
        user_text = (state["messages"][-1].content or "").strip().lower()
        
        # print("\n===== DEBUG START =====")
        # print("routing_keywords =", self.routing_keywords)
        # print("index + value =", [(i, k) for i, k in enumerate(self.routing_keywords)])
        # print("None items =", [i for i, k in enumerate(self.routing_keywords) if k is None])
        # print("user_text =", user_text, type(user_text))
        # print("===== DEBUG END =====\n")

        # # route to retriever if any routing keyword present
        # if any(k.lower() in user_text for k in self.routing_keywords):
        #     return {"messages": [AIMessage(content="TOOL: retriever")]}

        # ---- RAG-FIRST SEMANTIC ROUTING ----
        retriever = self.retriever_obj.load_retriever()
        docs = retriever.invoke(user_text)

        # If retriever finds any matching docs, send to RAG
        if docs and len(docs) > 0:
            return {"messages": [AIMessage(content="TOOL: retriever")]}

        prompt = ChatPromptTemplate.from_template(self.direct_answer_prompt)
        chain = prompt | self.llm | StrOutputParser()
        response = chain.invoke({"question": state["messages"][-1].content})
        return {"messages": [AIMessage(content=response)]}

    def _retriever(self, state: AgentState):
        print("--- RETRIEVER ---")
        query = self._latest_human_query(state["messages"])

        retriever = self.retriever_obj.load_retriever()
        docs = retriever.invoke(query)

        context = self._format_docs(docs)
        return {"messages": [AIMessage(content=context)]}

    def _grade(self, state: AgentState) -> Literal["generator", "rewriter", "fallback"]:
        print("--- GRADER ---")
        question = self._latest_human_query(state["messages"])
        docs_text = state["messages"][-1].content or ""
        rewrite_count = int(state.get("rewrite_count", 0))

        if rewrite_count >= self.max_rewrites:
            return "fallback" if self.fallback_enabled else "generator"

        prompt = PromptTemplate(
            template=self.grader_prompt,
            input_variables=["question", "docs"],
        )
        chain = prompt | self.llm | StrOutputParser()
        score = (chain.invoke({"question": question, "docs": docs_text}) or "").lower().strip()

        return "generator" if "yes" in score else "rewriter"

    def _generate(self, state: AgentState):
        print("--- GENERATE ---")
        question = self._latest_human_query(state["messages"])
        docs_text = state["messages"][-1].content or ""

        # your product bot prompt from registry
        prompt = ChatPromptTemplate.from_template(
            PROMPT_REGISTRY[PromptType.PRODUCT_BOT].template
        )
        chain = prompt | self.llm | StrOutputParser()
        response = chain.invoke({"context": docs_text, "question": question})
        return {"messages": [AIMessage(content=response)]}

    def _rewrite(self, state: AgentState):
        print("--- REWRITE ---")
        rc = int(state.get("rewrite_count", 0)) + 1
        question = self._latest_human_query(state["messages"])

        rewritten = self.llm.invoke(
            [HumanMessage(content=f"Rewrite this query to be clearer and more searchable:\n{question}")]
        )

        # Add rewritten query back as a HumanMessage so retriever sees it next
        return {"rewrite_count": rc, "messages": [HumanMessage(content=rewritten.content)]}

    def _fallback(self, state: AgentState):
        print("--- FALLBACK ---")
        question = self._latest_human_query(state["messages"])

        msg = f"{self.fallback_message}\n\nQuestion was: {question}"
        return {"messages": [AIMessage(content=msg)]}

    # ---------- Build Workflow ----------
    def _build_workflow(self):
        workflow = StateGraph(self.AgentState)

        workflow.add_node("Assistant", self._assistant)
        workflow.add_node("Retriever", self._retriever)
        workflow.add_node("Generator", self._generate)
        workflow.add_node("Rewriter", self._rewrite)
        workflow.add_node("Fallback", self._fallback)

        workflow.add_edge(START, "Assistant")

        # Assistant decides to call retriever or stop
        workflow.add_conditional_edges(
            "Assistant",
            lambda state: "Retriever" if "TOOL: retriever" in state["messages"][-1].content else END,
            {"Retriever": "Retriever", END: END},
        )

        # Retriever -> grade -> route
        workflow.add_conditional_edges(
            "Retriever",
            self._grade,
            {"generator": "Generator", "rewriter": "Rewriter", "fallback": "Fallback"},
        )

        workflow.add_edge("Generator", END)
        workflow.add_edge("Fallback", END)
        workflow.add_edge("Rewriter", "Assistant")

        return workflow

    # ---------- Public Run ----------
    def run(self, query: str, thread_id: str = "default_thread") -> str:
        result = self.app.invoke(
            {"messages": [HumanMessage(content=query)], "rewrite_count": 0},
            config={
                "configurable": {"thread_id": thread_id},
                "recursion_limit": self.recursion_limit,
            },
        )
        return result["messages"][-1].content


if __name__ == "__main__":
    rag_agent = AgenticRAG()

    #print("\nFinal Answer:\n", rag_agent.run("Can you suggest any sunscreen for women specially for sensitive skin?"))
    print("\nFinal Answer:\n", rag_agent.run("“Summarize reviews for google pixel and recommend which is best among iphone 15, 17 and google with respect to new AI .”"))
    #print("\nFinal Answer:\n", rag_agent.run("“Write a love poem about the moon.”"))