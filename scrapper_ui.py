import streamlit as st
import asyncio
from prod_assistant.etl.data_scrapper import FlipkartScraper
import os

# Windows safe
import sys, os as os_sys
if os_sys.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

st.title("📦 Flipkart Product Review Scraper")

# Initialize session state
if "product_inputs" not in st.session_state:
    st.session_state.product_inputs = [""]

def add_product_input():
    st.session_state.product_inputs.append("")

st.subheader("📝 Optional Product Description")
product_description = st.text_area("Enter product description (used as an extra search keyword):")

st.subheader("🛒 Product Names")
updated_inputs = []
for i, val in enumerate(st.session_state.product_inputs):
    input_val = st.text_input(f"Product {i+1}", value=val, key=f"product_{i}")
    updated_inputs.append(input_val)
st.session_state.product_inputs = updated_inputs

st.button("➕ Add Another Product", on_click=add_product_input)

max_products = st.number_input("How many products per search?", min_value=1, max_value=10, value=1)
review_count = st.number_input("How many reviews per product?", min_value=1, max_value=10, value=2)

output_path = "data/product_reviews.csv"
scraper = FlipkartScraper(output_dir="data")

async def scrape_all(products):
    final_data = []
    for query in products:
        st.info(f"🔍 Searching for: {query}")
        results = await scraper.scrape_flipkart_products(query, max_products=max_products, review_count=review_count)
        final_data.extend(results)
    return final_data

if st.button("🚀 Start Scraping"):
    product_inputs = [p.strip() for p in st.session_state.product_inputs if p.strip()]
    if product_description.strip():
        product_inputs.append(product_description.strip())

    if not product_inputs:
        st.warning("⚠️ Please enter at least one product name or a product description.")
    else:
        # Run async scraper safely
        final_data = asyncio.run(scrape_all(product_inputs))

        # Remove duplicates by product_id
        unique_products = {}
        for row in final_data:
            if row[0] not in unique_products:
                unique_products[row[0]] = row
        final_data = list(unique_products.values())

        # Save CSV
        scraper.save_to_csv(final_data, filename=output_path)
        st.session_state["scraped_data"] = final_data

        st.success(f"✅ Data saved to `{output_path}`")
        with open(output_path, "rb") as f:
            st.download_button("📥 Download CSV", data=f, file_name="product_reviews.csv")