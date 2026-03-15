import streamlit as st
import os

# FIXED IMPORTS
from prod_assistant.etl.data_scrapper_working_single import FlipkartScraper
from prod_assistant.etl.data_scrapper_multi_running import scrape_multiple_products
from prod_assistant.etl.data_ingestion import DataIngestion

st.title("📦 Product Review Scraper")

output_path = "data/product_reviews.csv"

if "product_inputs" not in st.session_state:
    st.session_state.product_inputs = [""]


def add_product_input():
    st.session_state.product_inputs.append("")


st.subheader("📝 Optional Product Description")
product_description = st.text_area("Enter product description (optional extra keyword):")

st.subheader("🛒 Product Names")
updated_inputs = []

for i, val in enumerate(st.session_state.product_inputs):
    input_val = st.text_input(f"Product {i+1}", value=val, key=f"product_{i}")
    updated_inputs.append(input_val)

st.session_state.product_inputs = updated_inputs

st.button("➕ Add Another Product", on_click=add_product_input)

max_products = st.number_input("How many products per search?", min_value=1, max_value=10, value=1)
review_count = st.number_input("How many reviews per product to save in CSV?", min_value=1, max_value=50, value=5)

if st.button("🚀 Start Scraping"):

    product_inputs = [p.strip() for p in st.session_state.product_inputs if p.strip()]

    if product_description.strip():
        product_inputs.append(product_description.strip())

    if not product_inputs:
        st.warning("⚠️ Please enter at least one product name or a product description.")
    else:
        st.write("🧹 Cleaning inputs...")
        queries = product_inputs

        # MULTIPLE QUERIES?
        if len(queries) > 1:
            st.info("🔄 Running multi-product scraping...")

            final_data = scrape_multiple_products(
                queries=queries,
                max_products=int(max_products),
                review_count=int(review_count),
                output_csv=output_path,
                chrome_version_main=145,
                headless=False,
                retries=2
            )

        else:
            st.info("🔍 Running single query scraping.....")
            scraper = FlipkartScraper(output_dir="data", chrome_version_main=145, headless=False)

            final_data = scraper.scrape_flipkart_products(
                queries[0],
                max_products=int(max_products),
                review_count=int(review_count)
            )

            # save manually
            scraper.save_to_csv(final_data, output_path)

        # Deduplicate
        final_data = list({row[0]: row for row in final_data}.values())

        st.success("✅ Data saved to data/product_reviews.csv")

        with open(output_path, "rb") as f:
            st.download_button("📥 Download CSV", data=f, file_name="product_reviews.csv")

        st.session_state["scraped_data"] = final_data

if "scraped_data" in st.session_state and st.button("🧠 Store in Vector DB (AstraDB)"):
    with st.spinner("📡 Ingesting to AstraDB..."):
        try:
            ingestion = DataIngestion(csv_path=output_path)
            ingestion.run_pipeline()
            st.success("✅ Data ingested to AstraDB!")
        except Exception as e:
            st.error("❌ Ingestion failed!")
            st.exception(e)
