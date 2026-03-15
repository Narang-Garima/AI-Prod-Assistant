# src/prod_assistant/etl/data_ingestion.py

import os
import re
import math
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_astradb import AstraDBVectorStore

from prod_assistant.utils.model_loader import ModelLoader
from prod_assistant.utils.config_loader import load_config


def _safe_str(x) -> str:
    if x is None:
        return "N/A"
    # pandas NaN
    try:
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return "N/A"
    except Exception:
        pass
    s = str(x).strip()
    if not s or s.lower() in {"nan", "none", "null", "inf", "-inf"}:
        return "N/A"
    return s


class DataIngestion:
    """
    CSV -> (split reviews) -> LangChain Documents -> AstraDB Vector Store
    """

    def __init__(self, csv_path: Optional[str] = None):
        print("Initializing DataIngestion pipeline...")

        self.model_loader = ModelLoader()
        self.config = load_config()

        self._load_env_variables()
        self._test_astra_connection()

        self.csv_path = csv_path or self._get_default_csv_path()
        self.product_data = self._load_csv(self.csv_path)

        self.vectorstore: Optional[AstraDBVectorStore] = None

    def _load_env_variables(self) -> None:
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

        self.db_api_endpoint = _safe_str(os.getenv("ASTRA_DB_API_ENDPOINT"))
        self.db_application_token = _safe_str(os.getenv("ASTRA_DB_APPLICATION_TOKEN"))
        self.db_keyspace = _safe_str(os.getenv("ASTRA_DB_KEYSPACE"))
        self.google_api_key = _safe_str(os.getenv("GOOGLE_API_KEY"))

        if not self.db_application_token.startswith("AstraCS:"):
            raise EnvironmentError("ASTRA_DB_APPLICATION_TOKEN must start with 'AstraCS:'")

        if self.db_keyspace == "N/A":
            raise EnvironmentError("ASTRA_DB_KEYSPACE is empty. Set it (often 'default_keyspace').")

    def _test_astra_connection(self) -> None:
        from astrapy import DataAPIClient

        client = DataAPIClient(self.db_application_token)
        db = client.get_database_by_api_endpoint(self.db_api_endpoint)

        try:
            names = db.list_collection_names(self.db_keyspace)
        except TypeError:
            try:
                names = db.list_collection_names(keyspace=self.db_keyspace)
            except TypeError:
                names = db.list_collection_names()

        print(f"Astra connection OK. Collections in '{self.db_keyspace}': {names}")

    def _get_default_csv_path(self) -> str:
        csv_path = os.path.join(os.getcwd(), "data", "product_reviews.csv")
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"CSV file not found at: {csv_path}")
        return csv_path

    def _load_csv(self, csv_path: str) -> pd.DataFrame:
        df = pd.read_csv(csv_path)

        expected = {"product_id", "product_title", "rating", "total_reviews", "price", "top_reviews"}
        if not expected.issubset(set(df.columns)):
            raise ValueError(f"CSV must contain columns: {expected}")

        # sanitize key columns
        for c in ["product_id", "product_title", "rating", "total_reviews", "price", "top_reviews"]:
            df[c] = df[c].apply(_safe_str)

        return df

    def _split_top_reviews(self, text: str) -> List[str]:
        if not text or text == "N/A":
            return []
        parts = re.split(r"\s*\|\|\s*", str(text))
        cleaned: List[str] = []
        for p in parts:
            p = p.replace("READ MORE", " ").strip()
            p = re.sub(r"\s+", " ", p).strip()
            if len(p) >= 25:
                cleaned.append(p)
        return cleaned or [str(text).strip()]

    def transform_data(self) -> List[Document]:
        documents: List[Document] = []

        for _, row in self.product_data.iterrows():
            base_metadata = {
                "product_id": _safe_str(row["product_id"]),
                "product_title": _safe_str(row["product_title"]),
                "rating": _safe_str(row["rating"]),
                "total_reviews": _safe_str(row["total_reviews"]),
                "price": _safe_str(row["price"]),
            }

            reviews = self._split_top_reviews(_safe_str(row["top_reviews"]))
            for idx, review in enumerate(reviews, start=1):
                meta = dict(base_metadata)
                meta["review_index"] = int(idx)  # safe int
                documents.append(Document(page_content=_safe_str(review), metadata=meta))

        print(f"Transformed {len(documents)} documents.")
        return documents

    def get_vectorstore(self) -> AstraDBVectorStore:
        collection_name = self.config["astra_db"]["collection_name"]

        return AstraDBVectorStore(
            embedding=self.model_loader.load_embeddings(),
            collection_name=collection_name,
            api_endpoint=self.db_api_endpoint,
            token=self.db_application_token,
            namespace=self.db_keyspace,
        )

    def store_in_vector_db(self, documents: List[Document]) -> Tuple[AstraDBVectorStore, List[str]]:
        vstore = self.get_vectorstore()
        inserted_ids = vstore.add_documents(documents)
        print(f"Inserted {len(inserted_ids)} documents into AstraDB.")
        self.vectorstore = vstore
        return vstore, inserted_ids

    def run_pipeline(self) -> Tuple[AstraDBVectorStore, List[str]]:
        documents = self.transform_data()
        return self.store_in_vector_db(documents)


if __name__ == "__main__":
    ingestion = DataIngestion()
    ingestion.run_pipeline()
