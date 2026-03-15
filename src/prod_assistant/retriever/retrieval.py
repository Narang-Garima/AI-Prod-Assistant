# src/prod_assistant/retrieval/retriever.py

import os
import re
from pathlib import Path
from typing import List, Any

from dotenv import load_dotenv
from langchain_astradb import AstraDBVectorStore
from langchain.retrievers import ContextualCompressionRetriever
from langchain.retrievers.document_compressors import LLMChainFilter
from langchain_core.documents import Document

from prod_assistant.utils.config_loader import load_config
from prod_assistant.utils.model_loader import ModelLoader

from prod_assistant.evaluation.ragas_eval import (
    evaluate_context_precision,
    evaluate_response_relevancy,
)


def _safe_str(x: Any, default: str = "N/A") -> str:
    s = "" if x is None else str(x).strip()
    return s if s else default


def _is_noise_review(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return True
    if t in {"no reviews found", "n/a"}:
        return True

    # Kill obvious "spec summary blocks" that sometimes get scraped as reviews
    # e.g. "+2955 Camera 4.6 Battery 4.3 ..."
    if re.search(r"^\+\d+\s+camera\s+\d", t):
        return True
    if "camera" in t and "battery" in t and "display" in t and "performance" in t and t.startswith("+"):
        return True

    # Very short fragments are noise
    if len(t) < 25:
        return True

    return False


def _doc_dedupe_key(d: Document) -> str:
    meta = d.metadata or {}
    pid = meta.get("product_id") or meta.get("pid") or ""
    title = meta.get("product_title") or ""
    text = re.sub(r"\s+", " ", (d.page_content or "").strip().lower())
    return f"{pid}||{title}||{text[:180]}"


def format_docs_as_context_strings(docs: List[Document]) -> List[str]:
    """
    RAGAS expects contexts: List[str]
    """
    out: List[str] = []
    for d in docs:
        meta = d.metadata or {}
        out.append(
            f"Title: {_safe_str(meta.get('product_title'))}\n"
            f"Price: {_safe_str(meta.get('price'))}\n"
            f"Rating: {_safe_str(meta.get('rating'))}\n"
            f"Review:\n{(d.page_content or '').strip()}"
        )
    return out


def build_grounded_response(query: str, docs: List[Document], max_items: int = 5) -> str:
    """
    This is the MOST IMPORTANT change:
    Your earlier response was unrelated to contexts, so Context Precision became 0.
    This response always quotes evidence from retrieved reviews.
    """
    if not docs:
        return "I couldn’t find relevant review text in the database for this query."

    lines = [f"Based on the retrieved reviews for: {query}\n"]

    for i, d in enumerate(docs[:max_items], 1):
        meta = d.metadata or {}
        title = _safe_str(meta.get("product_title"))
        rating = _safe_str(meta.get("rating"))
        price = _safe_str(meta.get("price"))
        snippet = re.sub(r"\s+", " ", (d.page_content or "").strip())
        snippet = snippet[:220] + ("..." if len(snippet) > 220 else "")

        lines.append(
            f"{i}. {title} | Rating: {rating} | Price: {price}\n"
            f"   Evidence: {snippet}"
        )

    lines.append("\nThese points are taken directly from the retrieved review text.")
    return "\n".join(lines)


class Retriever:
    def __init__(self):
        self.model_loader = ModelLoader()
        self.config = load_config()
        self._load_env_variables()

        self.vstore = None
        self.retriever_instance = None

    # -------------------------
    # ENV LOADING (consistent with ingestion)
    # -------------------------
    def _load_env_variables(self):
        load_dotenv(
            dotenv_path=Path(__file__).resolve().parents[3] / ".env",
            override=True,
        )

        required_vars = [
            "GOOGLE_API_KEY",
            "ASTRA_DB_API_ENDPOINT",
            "ASTRA_DB_APPLICATION_TOKEN",
            "ASTRA_DB_KEYSPACE",
        ]
        missing_vars = [v for v in required_vars if not (os.getenv(v) or "").strip()]
        if missing_vars:
            raise EnvironmentError(f"Missing environment variables: {missing_vars}")

        self.google_api_key = os.getenv("GOOGLE_API_KEY").strip()
        self.db_api_endpoint = os.getenv("ASTRA_DB_API_ENDPOINT").strip()
        self.db_application_token = os.getenv("ASTRA_DB_APPLICATION_TOKEN").strip()
        self.db_keyspace = os.getenv("ASTRA_DB_KEYSPACE").strip()

    # -------------------------
    # VECTORSTORE HANDLE
    # -------------------------
    def _get_vectorstore(self) -> AstraDBVectorStore:
        if self.vstore is None:
            collection_name = self.config["astra_db"]["collection_name"]
            self.vstore = AstraDBVectorStore(
                embedding=self.model_loader.load_embeddings(),
                collection_name=collection_name,
                api_endpoint=self.db_api_endpoint,
                token=self.db_application_token,
                namespace=self.db_keyspace,
            )
        return self.vstore

    # -------------------------
    # LOAD RETRIEVER (toggle compression)
    # -------------------------
    def load_retriever(self):
        vstore = self._get_vectorstore()

        top_k = int(self.config.get("retriever", {}).get("top_k", 5))
        fetch_k = int(self.config.get("retriever", {}).get("fetch_k", 50))
        lambda_mult = float(self.config.get("retriever", {}).get("lambda_mult", 0.7))

        use_compression = bool(self.config.get("retriever", {}).get("use_compression", False))

        print(f"TOP_K from config: {top_k}")
        print(f"USE_COMPRESSION: {use_compression}")

        mmr_retriever = vstore.as_retriever(
            search_type="mmr",
            search_kwargs={"k": top_k, "fetch_k": fetch_k, "lambda_mult": lambda_mult},
        )

        if not self.retriever_instance:
            if use_compression:
                llm = self.model_loader.load_llm()
                compressor = LLMChainFilter.from_llm(llm)
                self.retriever_instance = ContextualCompressionRetriever(
                    base_compressor=compressor,
                    base_retriever=mmr_retriever,
                )
            else:
                self.retriever_instance = mmr_retriever

            print("Retriever loaded successfully.")

        return self.retriever_instance

    # -------------------------
    # CALL RETRIEVER + CLEANUP
    # -------------------------
    def call_retriever(self, query: str) -> List[Document]:
        retriever = self.load_retriever()
        results = retriever.invoke(query)
        print("FINAL returned docs (raw):", len(results))

        # Normalize tuples -> Document (safety)
        normalized: List[Document] = []
        for r in results:
            normalized.append(r[0] if isinstance(r, tuple) else r)

        # Filter noise + dedupe
        cleaned: List[Document] = []
        seen = set()
        for d in normalized:
            if _is_noise_review(d.page_content or ""):
                continue
            key = _doc_dedupe_key(d)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(d)

        print("FINAL returned docs (cleaned):", len(cleaned))
        return cleaned


# -------------------------
# MAIN TEST BLOCK
# -------------------------
if __name__ == "__main__":
    user_query = "Can you suggest any sunscreen for women specially for sensitive skin?"

    retriever_obj = Retriever()
    retrieved_docs = retriever_obj.call_retriever(user_query)

    print("\n--- DEBUG RETRIEVAL ---")
    print("Total docs retrieved:", len(retrieved_docs))

    for i, d in enumerate(retrieved_docs, 1):
        title = (d.metadata or {}).get("product_title", "N/A")
        print(f"{i}. {title} :: {(d.page_content or '')[:90]}")

    # contexts must be List[str] for ragas==0.3.4
    contexts = format_docs_as_context_strings(retrieved_docs)
    print("\nContext chunks:", len(contexts))

    # ✅ grounded response (fixes context precision)
    response = build_grounded_response(user_query, retrieved_docs, max_items=5)
    print("\n--- GROUNDED RESPONSE ---")
    print(response)

    context_score = evaluate_context_precision(user_query, response, contexts)
    relevancy_score = evaluate_response_relevancy(user_query, response, contexts)

    print("\n--- Evaluation Metrics ---")
    print("Context Precision Score:", context_score)
    print("Response Relevancy Score:", relevancy_score)
