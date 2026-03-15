# src/prod_assistant/etl/data_scrapper_multi.py
# FINAL STABLE VERSION — NO THREADING, NO ERRORS, ONE CSV

import time
from typing import List, Dict

from prod_assistant.etl.data_scrapper_working_single import FlipkartScraper


def scrape_multiple_products(
        queries: List[str],
        max_products: int = 2,
        review_count: int = 3,
        output_csv: str = "data/multi_output.csv",
        chrome_version_main: int = 145,
        headless: bool = False,
        retries: int = 2,
):
    """
    FINAL SAFE VERSION:
    - Sequential scraping (required for undetected_chromedriver on Windows)
    - Retries
    - One combined CSV output
    - No per-query CSVs
    """

    scraper = FlipkartScraper(
        output_dir="data",
        chrome_version_main=chrome_version_main,
        headless=headless,
    )

    all_rows = []

    for q in queries:
        print(f"\n🔍 Scraping query: {q}")

        for attempt in range(1, retries + 1):
            try:
                rows = scraper.scrape_flipkart_products(
                    q,
                    max_products=max_products,
                    review_count=review_count
                )

                print(f"   ✔ Completed '{q}' → {len(rows)} rows")
                all_rows.extend(rows)
                break

            except Exception as e:
                print(f"   ❌ Error scraping '{q}' (Attempt {attempt}/{retries}) → {e}")
                time.sleep(1)

                if attempt == retries:
                    print(f"   💀 Giving up on '{q}'")

    # Save one final CSV
    scraper.save_to_csv(all_rows, output_csv)

    print("\n🎉 MULTI-SCRAPING COMPLETE")
    print(f"📁 Saved CSV: {output_csv}")
    print(f"🔢 Total rows: {len(all_rows)}")

    return all_rows


# ---------------------------------------------------
# TEST HOOK
# ---------------------------------------------------

if __name__ == "__main__":
    queries = [
        "iphone 16",
        "sunscreen sensitive skin",
        "google pixel 8",
        "samsung galaxy s24",
    ]

    scrape_multiple_products(
        queries=queries,
        max_products=2,
        review_count=3,
        output_csv="data/multi_output.csv",
        chrome_version_main=145,
        headless=False,
        retries=2,
    )
