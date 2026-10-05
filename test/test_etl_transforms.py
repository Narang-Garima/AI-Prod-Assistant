import pandas as pd

from prod_assistant.etl.data_ingestion import DataIngestion
from prod_assistant.etl.data_scrapper_working_single import (
    _extract_ids_from_href,
    clean_review_card_text,
)


def test_ingestion_splits_reviews_into_attributed_documents():
    ingestion = DataIngestion.__new__(DataIngestion)
    ingestion.product_data = pd.DataFrame(
        [
            {
                "product_id": "P-1",
                "product_title": "Example Phone",
                "rating": "4.4",
                "total_reviews": "125",
                "price": "₹20,000",
                "top_reviews": (
                    "Battery life is strong enough for a full day. || "
                    "The camera performs well in normal daylight."
                ),
            }
        ]
    )

    documents = ingestion.transform_data()

    assert len(documents) == 2
    assert documents[0].metadata["product_id"] == "P-1"
    assert documents[0].metadata["review_index"] == 1
    assert documents[1].metadata["review_index"] == 2


def test_scraper_helpers_extract_ids_and_remove_review_ui_noise():
    href = "/example/p/itmABC123?pid=MOBXYZ789"
    assert _extract_ids_from_href(href) == ("MOBXYZ789", "itmABC123")

    cleaned = clean_review_card_text(
        "5 Excellent Verified Buyer The battery lasts all day and the camera is reliable. 2 months ago"
    )
    assert "Verified Buyer" not in cleaned
    assert "months ago" not in cleaned
    assert "battery lasts all day" in cleaned
