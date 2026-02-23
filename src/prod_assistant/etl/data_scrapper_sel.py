import csv
import os
import re
from time import sleep
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup


class FlipkartScraper:
    def __init__(self, output_dir="data"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    # -----------------------------
    # Create Chrome Driver
    # -----------------------------
    def _create_driver(self):
        options = Options()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        # Headless mode optional:
        # options.add_argument("--headless=new")
        driver = webdriver.Chrome(options=options)
        return driver

    # -----------------------------
    # Get Top Reviews of a Product
    # -----------------------------
    def get_top_reviews(self, product_url, count=2):
        if not product_url.startswith("http"):
            return "No reviews found"

        driver = None
        reviews = []

        try:
            driver = self._create_driver()
            driver.get(product_url)

            # Wait until reviews block is present
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div._16PBlm"))
            )

            # Close login popup if exists
            try:
                close_btn = driver.find_element(By.XPATH, "//button[contains(text(), '✕')]")
                close_btn.click()
            except:
                pass

            # Scroll to load reviews
            for _ in range(4):
                ActionChains(driver).send_keys(Keys.END).perform()
                sleep(1.5)

            soup = BeautifulSoup(driver.page_source, "html.parser")
            review_blocks = soup.select("div._16PBlm, div._27M-vq, div.col.EPCmJX, div._6K-7Co")

            seen = set()
            for block in review_blocks:
                text = block.get_text(separator=" ", strip=True)
                if text and text not in seen:
                    reviews.append(text)
                    seen.add(text)
                if len(reviews) >= count:
                    break

        except Exception as e:
            print("Error in get_top_reviews:", e)

        finally:
            if driver:
                driver.quit()

        return " || ".join(reviews) if reviews else "No reviews found"

    # -----------------------------
    # Scrape Products from Search
    # -----------------------------
    def scrape_flipkart_products(self, query, max_products=3, review_count=2):
        driver = None
        products = []

        try:
            driver = self._create_driver()
            search_url = f"https://www.flipkart.com/search?q={query.replace(' ', '+')}"
            driver.get(search_url)

            # Wait until product listings load
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div._1AtVbE"))
            )

            # Close login popup
            try:
                close_btn = driver.find_element(By.XPATH, "//button[contains(text(), '✕')]")
                close_btn.click()
            except:
                pass

            sleep(2)

            items = driver.find_elements(By.CSS_SELECTOR, "div._1AtVbE")
            # Keep only items with product links
            items = [item for item in items if item.find_elements(By.CSS_SELECTOR, "a[href*='/p/']")]

            for item in items[:max_products]:
                try:
                    # Title
                    try:
                        title = item.find_element(By.CSS_SELECTOR, "a[title]").get_attribute("title")
                    except:
                        try:
                            title = item.find_element(By.CSS_SELECTOR, "div._4rR01T").text.strip()
                        except:
                            title = "N/A"

                    # Price
                    try:
                        price = item.find_element(By.CSS_SELECTOR, "div._30jeq3").text.strip()
                    except:
                        price = "N/A"

                    # Rating
                    try:
                        rating = item.find_element(By.CSS_SELECTOR, "div._3LWZlK").text.strip()
                    except:
                        rating = "N/A"

                    # Total reviews
                    try:
                        reviews_text = item.find_element(By.CSS_SELECTOR, "span._2_R_DZ").text.strip()
                        match = re.search(r"\d+(,\d+)?(?=\s+Reviews)", reviews_text)
                        total_reviews = match.group(0) if match else "N/A"
                    except:
                        total_reviews = "N/A"

                    # Product link and ID
                    link_el = item.find_element(By.CSS_SELECTOR, "a[href*='/p/']")
                    href = link_el.get_attribute("href")
                    product_link = href if href.startswith("http") else "https://www.flipkart.com" + href
                    match = re.findall(r"/p/(itm[0-9A-Za-z]+)", href)
                    product_id = match[0] if match else "N/A"

                    # Top reviews
                    top_reviews = self.get_top_reviews(product_link, count=review_count)

                    products.append([
                        product_id,
                        title,
                        rating,
                        total_reviews,
                        price,
                        top_reviews
                    ])

                except Exception as e:
                    print("Error processing item:", e)
                    continue

        except Exception as e:
            print("Error in scrape_flipkart_products:", e)

        finally:
            if driver:
                driver.quit()

        return products

    # -----------------------------
    # Save to CSV
    # -----------------------------
    def save_to_csv(self, data, filename="product_reviews.csv"):
        if os.path.isabs(filename):
            path = filename
        elif os.path.dirname(filename):
            path = filename
            os.makedirs(os.path.dirname(path), exist_ok=True)
        else:
            path = os.path.join(self.output_dir, filename)

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "product_id", "product_title", "rating", "total_reviews", "price", "top_reviews"
            ])
            writer.writerows(data)
