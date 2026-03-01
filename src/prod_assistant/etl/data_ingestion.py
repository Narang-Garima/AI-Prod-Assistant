import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_astradb import AstraDBVectorStore

from prod_assistant.utils.model_loader import ModelLoader
from prod_assistant.utils.config_loader import load_config


class DataIngestion:
    """
    CSV -> (split reviews) -> LangChain Documents -> AstraDB Vector Store
    Includes a lightweight Astra connection check.
    """

    def __init__(self, csv_path: Optional[str] = None):
        print("Initializing DataIngestion pipeline...")

        self.model_loader = ModelLoader()
        self.config = load_config()

        self._load_env_variables()
        self._test_astra_connection()

        # Allow Streamlit or callers to pass a CSV path; fallback to default
        self.csv_path = csv_path or self._get_default_csv_path()
        self.product_data = self._load_csv(self.csv_path)

        # Optional cached handle
        self.vectorstore: Optional[AstraDBVectorStore] = None

    # -------------------------
    # ENV + SANITY CHECKS
    # -------------------------
    def _load_env_variables(self) -> None:
        # Load .env from project root reliably:
        # .../src/prod_assistant/etl/data_ingestion.py -> parents[3] == project root
        load_dotenv(dotenv_path=Path(__file__).resolve().parents[3] / ".env", override=True)

        required_vars = [
            "GOOGLE_API_KEY",
            "ASTRA_DB_API_ENDPOINT",
            "ASTRA_DB_APPLICATION_TOKEN",
            "ASTRA_DB_KEYSPACE",
        ]
        missing = [v for v in required_vars if not (os.getenv(v) or "").strip()]
        if missing:
            raise EnvironmentError(f"Missing environment variables: {missing}")

        self.db_api_endpoint = (os.getenv("ASTRA_DB_API_ENDPOINT") or "").strip()
        self.db_application_token = (os.getenv("ASTRA_DB_APPLICATION_TOKEN") or "").strip()
        self.db_keyspace = (os.getenv("ASTRA_DB_KEYSPACE") or "").strip()
        self.google_api_key = (os.getenv("GOOGLE_API_KEY") or "").strip()

        # Fail fast if token/keyspace look wrong
        if not self.db_application_token.startswith("AstraCS:"):
            raise EnvironmentError("ASTRA_DB_APPLICATION_TOKEN must start with 'AstraCS:' (Astra Data API token).")

        if not self.db_keyspace:
            raise EnvironmentError("ASTRA_DB_KEYSPACE is empty. Set it (often 'default_keyspace').")

    def _test_astra_connection(self) -> None:
        """
        Lightweight auth check. Compatible with astrapy 2.1.0 signatures.
        """
        from astrapy import DataAPIClient

        client = DataAPIClient(self.db_application_token)
        db = client.get_database_by_api_endpoint(self.db_api_endpoint)

        # astrapy 2.1.0: list_collection_names() does NOT accept namespace=
        try:
            names = db.list_collection_names(self.db_keyspace)  # positional keyspace
        except TypeError:
            try:
                names = db.list_collection_names(keyspace=self.db_keyspace)  # alternate kw
            except TypeError:
                names = db.list_collection_names()  # fallback

        print(f"Astra connection OK. Collections in '{self.db_keyspace}': {names}")

    # -------------------------
    # CSV LOADING
    # -------------------------
    def _get_default_csv_path(self) -> str:
        """
        Default CSV path: <project_cwd>/data/product_reviews.csv
        """
        csv_path = os.path.join(os.getcwd(), "data", "product_reviews.csv")
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"CSV file not found at: {csv_path}")
        return csv_path

    def _load_csv(self, csv_path: str) -> pd.DataFrame:
        df = pd.read_csv(csv_path)

        expected_columns = {
            "product_id",
            "product_title",
            "rating",
            "total_reviews",
            "price",
            "top_reviews",
        }
        if not expected_columns.issubset(set(df.columns)):
            raise ValueError(f"CSV must contain columns: {expected_columns}")

        return df

    # -------------------------
    # TRANSFORM: SPLIT REVIEWS
    # -------------------------
    def _split_top_reviews(self, text: str) -> List[str]:
        """
        Split concatenated review text into individual review strings.
        Your source appears to use '||' as a delimiter and contains 'READ MORE'.
        """
        if not text:
            return []

        t = str(text)

        # Primary split on "||"
        parts = re.split(r"\s*\|\|\s*", t)

        cleaned: List[str] = []
        for p in parts:
            p = p.replace("READ MORE", " ").strip()
            p = re.sub(r"\s+", " ", p).strip()
            if len(p) >= 25:  # drop tiny fragments
                cleaned.append(p)

        # If no delimiter present, keep the whole text
        return cleaned or [t.strip()]

    def transform_data(self) -> List[Document]:
        """
        Create one Document per individual review (better retrieval).
        """
        documents: List[Document] = []

        for _, row in self.product_data.iterrows():
            base_metadata = {
                "product_id": row["product_id"],
                "product_title": row["product_title"],
                "rating": row["rating"],
                "total_reviews": row["total_reviews"],
                "price": row["price"],
            }

            raw = str(row["top_reviews"]) if pd.notna(row["top_reviews"]) else ""
            reviews = self._split_top_reviews(raw)

            for idx, review in enumerate(reviews, start=1):
                meta = dict(base_metadata)
                meta["review_index"] = idx
                documents.append(Document(page_content=review, metadata=meta))

        print(f"Transformed {len(documents)} documents.")
        return documents

    # -------------------------
    # ASTRA VECTOR STORE
    # -------------------------
    def get_vectorstore(self) -> AstraDBVectorStore:
        """
        Connect to AstraDB vector store (same collection every time).
        This does NOT ingest. It just returns a handle to the collection.
        """
        collection_name = self.config["astra_db"]["collection_name"]

        vstore = AstraDBVectorStore(
            embedding=self.model_loader.load_embeddings(),
            collection_name=collection_name,
            api_endpoint=self.db_api_endpoint,
            token=self.db_application_token,
            namespace=self.db_keyspace,  # LangChain uses 'namespace' for keyspace
        )
        return vstore

    def store_in_vector_db(self, documents: List[Document]) -> Tuple[AstraDBVectorStore, List[str]]:
        """
        Insert documents into AstraDB and return (vectorstore, inserted_ids).
        """
        vstore = self.get_vectorstore()
        inserted_ids = vstore.add_documents(documents)
        print(f"Successfully inserted {len(inserted_ids)} documents into AstraDB.")
        self.vectorstore = vstore
        return vstore, inserted_ids

    def get_retriever(self, k: int = 4):
        """
        Return a retriever for the AstraDB collection.
        Works even if you didn't call run_pipeline() in this process.
        """
        vstore = self.vectorstore or self.get_vectorstore()
        return vstore.as_retriever(search_kwargs={"k": k})

    # -------------------------
    # PIPELINE
    # -------------------------
    def run_pipeline(self) -> Tuple[AstraDBVectorStore, List[str]]:
        """
        Ingest CSV into AstraDB. Returns (vectorstore, inserted_ids).
        """
        documents = self.transform_data()
        return self.store_in_vector_db(documents)


if __name__ == "__main__":
    ingestion = DataIngestion()
    vstore, inserted = ingestion.run_pipeline()

    # quick manual test
    query = "mini computer"
    results = vstore.similarity_search(query, k=4)
    for r in results:
        print("\n----")
        print(r.page_content)
        print(r.metadata)
        print("----\n")