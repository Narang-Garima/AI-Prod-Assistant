import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_astradb import AstraDBVectorStore
from langchain.retrievers import ContextualCompressionRetriever
from langchain.retrievers.document_compressors import LLMChainFilter

from prod_assistant.utils.config_loader import load_config
from prod_assistant.utils.model_loader import ModelLoader

from prod_assistant.evaluation.ragas_eval import (
    evaluate_context_precision,
    evaluate_response_relevancy,
)


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

        # IMPORTANT: toggle compression here
        use_compression = bool(self.config.get("retriever", {}).get("use_compression", False))

        print(f"TOP_K from config: {top_k}")
        print(f"USE_COMPRESSION: {use_compression}")

        mmr_retriever = vstore.as_retriever(
            search_type="mmr",
            search_kwargs={
                "k": top_k,
                "fetch_k": fetch_k,
                "lambda_mult": lambda_mult,
            },
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
                # Return base retriever directly (no filtering down to 1)
                self.retriever_instance = mmr_retriever

            print("Retriever loaded successfully.")

        return self.retriever_instance

    # -------------------------
    # CALL RETRIEVER + DEBUG (base vs compressed)
    # -------------------------
    def call_retriever(self, query):
        vstore = self._get_vectorstore()

        top_k = int(self.config.get("retriever", {}).get("top_k", 5))
        fetch_k = int(self.config.get("retriever", {}).get("fetch_k", 50))
        lambda_mult = float(self.config.get("retriever", {}).get("lambda_mult", 0.7))

        base_retriever = vstore.as_retriever(
            search_type="mmr",
            search_kwargs={"k": top_k, "fetch_k": fetch_k, "lambda_mult": lambda_mult},
        )
        base_docs = base_retriever.invoke(query)
        print("BASE retriever docs:", len(base_docs))

        retriever = self.load_retriever()
        results = retriever.invoke(query)
        print("FINAL returned docs:", len(results))

        # Normalize tuples -> Document (safety)
        normalized = []
        for r in results:
            normalized.append(r[0] if isinstance(r, tuple) else r)

        return normalized


# -------------------------
# MAIN TEST BLOCK
# -------------------------
if __name__ == "__main__":
    user_query = "Can you suggest phone like mini computer?"

    retriever_obj = Retriever()
    retrieved_docs = retriever_obj.call_retriever(user_query)

    print("\n--- DEBUG RETRIEVAL ---")
    print("Total docs retrieved:", len(retrieved_docs))

    for i, d in enumerate(retrieved_docs, 1):
        title = (d.metadata or {}).get("product_title", "N/A")
        print(f"{i}. {title} :: {d.page_content[:90]}")

    # -------------------------
    # FORMAT CONTEXT (ONE combined context string)
    # -------------------------
    def format_docs(docs):
        if not docs:
            return "No relevant documents found."

        formatted_chunks = []
        for d in docs:
            meta = d.metadata or {}
            formatted_chunks.append(
                f"Title: {meta.get('product_title', 'N/A')}\n"
                f"Price: {meta.get('price', 'N/A')}\n"
                f"Rating: {meta.get('rating', 'N/A')}\n"
                f"Review:\n{d.page_content.strip()}"
            )
        return "\n\n---\n\n".join(formatted_chunks)

    retrieved_contexts = [format_docs(retrieved_docs)]
    context_text = retrieved_contexts[0]
    print("\nContext length:", len(context_text))

    # -------------------------
    # TEST RESPONSE (grounded)
    # -------------------------
    response = (
        "Based on the retrieved reviews, a strong option is the phone described as extremely powerful "
        "and comparable to a mini supercomputer, which suggests excellent performance for heavy use and gaming."
    )

    context_score = evaluate_context_precision(user_query, response, retrieved_contexts)
    relevancy_score = evaluate_response_relevancy(user_query, response, retrieved_contexts)

    print("\n--- Evaluation Metrics ---")
    print("Context Precision Score:", context_score)
    print("Response Relevancy Score:", relevancy_score)