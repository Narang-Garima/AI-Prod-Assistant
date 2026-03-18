import csv
import os
from datetime import datetime, timezone
from uuid import uuid4

import streamlit as st

from prod_assistant.etl.data_scrapper_working_single import FlipkartScraper
from prod_assistant.etl.data_ingestion import DataIngestion


BASE_OUTPUT_CSV = "data/product_reviews.csv"
HISTORY_OUTPUT_CSV = "data/product_reviews_history.csv"


def ensure_history_csv(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        return
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "run_id",
                "scrape_timestamp_utc",
                "source_query",
                "product_id",
                "product_title",
                "rating",
                "total_reviews",
                "price",
                "top_reviews",
            ]
        )


def append_history_rows(path: str, rows: list, query: str, run_id: str, ts_utc: str) -> int:
    ensure_history_csv(path)
    with open(path, "a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        for row in rows:
            writer.writerow([run_id, ts_utc, query, *row])
    return len(rows)


st.title("Product Review Scraper")
st.caption(
    "This app keeps your existing `data/product_reviews.csv` workflow intact for vector ingestion, "
    "and also appends every scrape to `data/product_reviews_history.csv` for dashboard analytics."
)

if "product_inputs" not in st.session_state:
    st.session_state.product_inputs = [""]


def add_product_input() -> None:
    st.session_state.product_inputs.append("")


st.subheader("Optional Product Description")
product_description = st.text_area("Enter product description (optional extra keyword):")

st.subheader("Product Names")
updated_inputs = []
for index, value in enumerate(st.session_state.product_inputs):
    input_value = st.text_input(f"Product {index + 1}", value=value, key=f"product_{index}")
    updated_inputs.append(input_value)
st.session_state.product_inputs = updated_inputs

st.button("Add Another Product", on_click=add_product_input)

max_products = st.number_input("How many products per search?", min_value=1, max_value=20, value=2)
review_count = st.number_input("How many reviews per product to save in CSV?", min_value=1, max_value=100, value=5)

if st.button("Start Scraping"):
    queries = [product.strip() for product in st.session_state.product_inputs if product.strip()]
    if product_description.strip():
        queries.append(product_description.strip())

    if not queries:
        st.warning("Please enter at least one product query.")
    else:
        scraper = FlipkartScraper(output_dir="data", chrome_version_main=145, headless=False)
        run_id = f"run-{uuid4().hex}"
        scrape_timestamp_utc = datetime.now(timezone.utc).isoformat()

        all_rows = []
        total_history_rows = 0

        for query in queries:
            st.info(f"Scraping query: {query}")
            try:
                query_rows = scraper.scrape_flipkart_products(
                    query,
                    max_products=int(max_products),
                    review_count=int(review_count),
                )
            except Exception as error:
                st.error(f"Failed query '{query}': {error}")
                continue

            all_rows.extend(query_rows)
            added = append_history_rows(
                path=HISTORY_OUTPUT_CSV,
                rows=query_rows,
                query=query,
                run_id=run_id,
                ts_utc=scrape_timestamp_utc,
            )
            total_history_rows += added
            st.success(f"Captured {len(query_rows)} rows for '{query}' (history appended: {added}).")

        if all_rows:
            deduped_for_base = list({row[0]: row for row in all_rows}.values())
            scraper.save_to_csv(deduped_for_base, BASE_OUTPUT_CSV)

            st.success(f"Updated base CSV for vector ingestion: {BASE_OUTPUT_CSV}")
            st.success(f"Appended historical rows (no overwrite): {HISTORY_OUTPUT_CSV}")
            st.write(f"Run ID: `{run_id}`")
            st.write(f"Total rows written to history: **{total_history_rows}**")
            st.write(f"Rows written to base CSV (deduped by product_id): **{len(deduped_for_base)}**")

            with open(BASE_OUTPUT_CSV, "rb") as base_file:
                st.download_button(
                    "Download base CSV (product_reviews.csv)",
                    data=base_file,
                    file_name="product_reviews.csv",
                )

            with open(HISTORY_OUTPUT_CSV, "rb") as history_file:
                st.download_button(
                    "Download history CSV (product_reviews_history.csv)",
                    data=history_file,
                    file_name="product_reviews_history.csv",
                )

            st.session_state["scraped_data"] = deduped_for_base
        else:
            st.warning("No rows were scraped for the provided queries.")

if "scraped_data" in st.session_state and st.button("Store in Vector DB (AstraDB)"):
    with st.spinner("Ingesting base CSV into AstraDB..."):
        try:
            ingestion = DataIngestion(csv_path=BASE_OUTPUT_CSV)
            ingestion.run_pipeline()
            st.success("Data ingested to AstraDB from base CSV.")
        except Exception as error:
            st.error("Ingestion failed.")
            st.exception(error)
