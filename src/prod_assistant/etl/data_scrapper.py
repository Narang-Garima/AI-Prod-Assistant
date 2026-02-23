import csv
import re
import os
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import asyncio
import sys

# Windows safe
if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

class FlipkartScraper:
    def __init__(self, output_dir="data"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    async def get_top_reviews(self, product_url, count=2):
        """Get top reviews using async Playwright."""
        if not product_url.startswith("http"):
            return "No reviews found"

        reviews = []

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()
                page = await context.new_page()
                await page.goto(product_url, timeout=60000)
                await page.wait_for_timeout(3000)

                # Close popup
                try:
                    await page.locator("button:has-text('✕')").click(timeout=2000)
                except:
                    pass

                # Scroll to load reviews
                for _ in range(4):
                    await page.mouse.wheel(0, 3000)
                    await page.wait_for_timeout(1500)

                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")
                review_blocks = soup.select("div._27M-vq, div._6K-7Co")

                seen = set()
                for block in review_blocks:
                    text = block.get_text(separator=" ", strip=True)
                    if text and text not in seen:
                        reviews.append(text)
                        seen.add(text)
                    if len(reviews) >= count:
                        break

                await browser.close()
        except Exception as e:
            print("Review extraction error:", e, file=sys.stderr)

        return " || ".join(reviews) if reviews else "No reviews found"

    async def scrape_flipkart_products(self, query, max_products=5, review_count=2):
        """Scrape Flipkart products asynchronously."""
        products = []
        search_url = f"https://www.flipkart.com/search?q={query.replace(' ', '+')}"

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()
                page = await context.new_page()
                await page.goto(search_url, timeout=60000)
                await page.wait_for_timeout(3000)

                # Close popup
                try:
                    await page.locator("button:has-text('✕')").click(timeout=2000)
                except:
                    pass

                await page.wait_for_selector("div[data-id]", timeout=20000)
                items = await page.locator("div[data-id]").element_handles()
                items = items[:max_products]

                for item in items:
                    try:
                        href_el = await item.query_selector("a[href*='/p/']")
                        if not href_el:
                            continue
                        href = await href_el.get_attribute("href")
                        if not href:
                            continue
                        product_link = href if href.startswith("http") else "https://www.flipkart.com" + href
                        product_id_match = re.findall(r"/p/(itm[0-9A-Za-z]+)", href)
                        product_id = product_id_match[0] if product_id_match else "N/A"

                        # Title
                        try:
                            title_el = await item.query_selector("div._4rR01T")
                            title = (await title_el.inner_text()).strip() if title_el else href
                        except:
                            title = href

                        # Price
                        try:
                            price_el = await item.query_selector("div._30jeq3._1_WHN1")
                            price = (await price_el.inner_text()).strip() if price_el else "N/A"
                        except:
                            price = "N/A"

                        # Rating
                        try:
                            rating_el = await item.query_selector("div._3LWZlK")
                            rating = (await rating_el.inner_text()).strip() if rating_el else "N/A"
                        except:
                            rating = "N/A"

                        # Total reviews
                        try:
                            total_reviews_el = await item.query_selector("span._2_R_DZ")
                            total_reviews_text = (await total_reviews_el.inner_text()).strip() if total_reviews_el else ""
                            match = re.search(r"(\d+,?\d*) Reviews", total_reviews_text)
                            total_reviews = match.group(1) if match else "N/A"
                        except:
                            total_reviews = "N/A"

                        # Top reviews
                        top_reviews = await self.get_top_reviews(product_link, count=review_count)

                        products.append([
                            product_id,
                            title,
                            rating,
                            total_reviews,
                            price,
                            top_reviews
                        ])
                    except Exception as e:
                        print("Error processing item:", e, file=sys.stderr)
                        continue

                await browser.close()
        except Exception as e:
            print("Search page error:", e, file=sys.stderr)

        return products

    def save_to_csv(self, data, filename="product_reviews.csv"):
        """Save to CSV using tab delimiter."""
        path = os.path.join(self.output_dir, filename) if not os.path.isabs(filename) else filename
        os.makedirs(os.path.dirname(path), exist_ok=True)

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter='\t')
            writer.writerow(["product_id","product_title","rating","total_reviews","price","top_reviews"])
            writer.writerows(data)

# Usage example (async main)
async def main():
    scraper = FlipkartScraper()
    data = await scraper.scrape_flipkart_products("Apple iPhone 16 Pro Max", max_products=3, review_count=3)
    scraper.save_to_csv(data, "iphone_reviews.csv")

if __name__ == "__main__":
    asyncio.run(main())