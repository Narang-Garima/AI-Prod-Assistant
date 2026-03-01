import csv
import os
import re
import time
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from selenium_stealth import stealth


def create_stealth_driver():
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-notifications")
    options.add_argument("--start-maximized")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(options=options)
    stealth(
        driver,
        languages=["en-US", "en"],
        vendor="Google Inc.",
        platform="Win32",
        webgl_vendor="Intel Inc.",
        renderer="Intel Iris OpenGL Engine",
        fix_hairline=True,
    )
    return driver


class FlipkartScraper:
    def __init__(self, output_dir="data"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def get_top_reviews(self, product_url, count=2):
        driver = create_stealth_driver()
        try:
            if not product_url.startswith("http"):
                return "No reviews found"

            m_id = re.search(r"/p/(itm[0-9A-Za-z]+)", product_url)
            product_id = m_id.group(1) if m_id else None
            if product_id:
                reviews_url = re.sub(r"/p/(itm[0-9A-Za-z]+)", r"/product-reviews/\1", product_url)
                if "/product-reviews/" not in reviews_url:
                    reviews_url = f"https://www.flipkart.com/product-reviews/{product_id}"
            else:
                reviews_url = product_url
            driver.get(reviews_url)
            time.sleep(5)

            

            try:
                driver.find_element(By.XPATH, "//button[contains(text(), '✕')]").click()
                time.sleep(1)
            except Exception:
                pass

            try:
                wait_rev = WebDriverWait(driver, 8)
                wait_rev.until(EC.presence_of_element_located(
                    (By.XPATH, "//*[contains(text(), 'Certified') or contains(text(), 'Verified') or contains(text(), 'ago') or contains(text(), 'READ MORE')]")
                ))
            except Exception:
                pass

            for i in range(6):
                ActionChains(driver).send_keys(Keys.END).perform()
                time.sleep(2 + 0.5 * i)

            try:
                read_more = driver.find_elements(By.XPATH, "//span[contains(text(), 'READ MORE')]")
                for btn in read_more[:5]:
                    try:
                        driver.execute_script("arguments[0].click();", btn)
                        time.sleep(0.5)
                    except Exception:
                        pass
            except Exception:
                pass

            soup = BeautifulSoup(driver.page_source, "html.parser")
            selectors = (
                "div.t-ZTKy, div._27M-vq, div.col.EPCmJX, div._6K-7Co, div._16PBlm, "
                "div.qwjRop, div._2sc7ZR, div[class*='review'], "
                "div.t4xD1Q, div.RWJtE9, div.Afujtw, div.BseBiK, div.lfFUxn, div.olwU0Z, "
                "div.CXZSEo, div.VCplLH, div.PGj60j, div.H5bs2Y, div.pkKEsC, div.pc3tUw, "
                "div.uRvp6e, div.LhEIN3, div.BseBiK"
            )
            review_blocks = soup.select(selectors)

            nav_phrases = (
                "Flipkart A one-stop",
                "My Profile",
                "Wishlist",
                "Become a Seller",
                "Gift Cards",
                "24x7 Customer Care",
                "Download App",
                "Notification Preferences",
                "Advertise on Flipkart",
                "Everything in Minutes",
                "Grocery At wholesale",
                "Travel All your travel",
                "Search Icon Search Icon",
            )

            def looks_like_nav(text: str) -> bool:
                if not text:
                    return True
                t = text.strip()
                if len(t) < 40:
                    return True
                lower = t.lower()
                if "flipkart" in lower and "shopping" in lower:
                    return True
                return any(p in t for p in nav_phrases)

            def looks_like_review(text: str) -> bool:
                if not text:
                    return False
                t = text.strip()
                if len(t) < 40 or len(t) > 1200:
                    return False
                if looks_like_nav(t):
                    return False
                has_time = re.search(r"\d+\s*(months?|month|days?|day|years?|year)\s+ago", t, re.I)
                has_stars = "★" in t or re.search(r"\b[1-5]\s*star", t, re.I)
                has_markers = any(m in t for m in ("Certified Buyer", "Verified Buyer", "Bronze Reviewer", "Silver Reviewer", "Gold Reviewer"))
                return bool(has_time or has_stars or has_markers)

            # Collect candidate review texts from initial selector blocks
            candidates: list[str] = []
            for blk in review_blocks:
                txt = blk.get_text(separator=" ", strip=True)
                if looks_like_review(txt):
                    candidates.append(txt)

            # Fallback: scan the whole page if we didn't get enough
            if len(candidates) < count:
                for elem in soup.find_all(["div", "span", "p"]):
                    txt = elem.get_text(separator=" ", strip=True)
                    if looks_like_review(txt):
                        candidates.append(txt)
                        if len(candidates) >= count * 2:
                            break

            # Final fallback: use Selenium-level text near "Certified/Verified Buyer"
            if len(candidates) < count:
                try:
                    sel_elems = driver.find_elements(
                        By.XPATH,
                        "//*[contains(., 'Certified Buyer') or contains(., 'Verified Buyer')]",
                    )
                    for el in sel_elems:
                        txt = (el.text or "").strip()
                        if looks_like_review(txt):
                            candidates.append(txt)
                            if len(candidates) >= count * 3:
                                break
                except Exception:
                    pass

            # Deduplicate while preserving order
            seen = set()
            reviews: list[str] = []
            for txt in candidates:
                if txt not in seen:
                    reviews.append(txt[:500])
                    seen.add(txt)
                if len(reviews) >= count:
                    break

            return " || ".join(reviews) if reviews else "No reviews found"
        except Exception:
            return "No reviews found"
        finally:
            driver.quit()

    def scrape_flipkart_products(self, query, max_products=1, review_count=2):
        driver = create_stealth_driver()
        wait = WebDriverWait(driver, 12)
        try:
            search_url = f"https://www.flipkart.com/search?q={query.replace(' ', '+')}"
            driver.get(search_url)

            try:
                wait.until(EC.element_to_be_clickable((By.XPATH, "//button.[contains(text(), '✕')]"))).click()
                time.sleep(1)
            except Exception:
                pass

            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-id]")))
            items = driver.find_elements(By.CSS_SELECTOR, "div[data-id]")[:max_products]

            products = []
            for idx, item in enumerate(items):
                try:
                    full_text = item.text

                    # ---- title ---- parse from card text (first real line after "Add to Compare")
                    title = None
                    selector_used = None
                    for sel in ["div.KzDlHZ", "div._4rR01T", "a[title]"]:
                        try:
                            el = item.find_element(By.CSS_SELECTOR, sel)
                            title = (el.get_attribute("title") if sel == "a[title]" else el.text).strip()
                            if title and len(title) < 200:
                                selector_used = sel
                                break
                        except Exception:
                            continue
                    if not title or len(title) > 200:
                        lines = [l.strip() for l in full_text.split("\n") if l.strip()]
                        for line in lines:
                            if line == "Add to Compare":
                                continue
                            if re.match(r"^\d+\.\d+", line):
                                continue
                            if len(line) > 15 and "₹" not in line and " Ratings" not in line:
                                title = line[:200]
                                break
                        title = title or "N/A"

                    # ---- price ----
                    price = "N/A"
                    try:
                        price_el = item.find_element(
                            By.XPATH,
                            ".//*[contains(text(),'₹') and normalize-space() != '']"
                        )
                        price = price_el.text.strip()
                    except Exception:
                        m = re.search(r"₹[\d,]+", full_text)
                        price = m.group(0) if m else "N/A"

                    # ---- rating ---- e.g. "4.65" from "4.656,735 Ratings"
                    rating = "N/A"
                    m = re.search(r"(\d\.\d{1,2})(?=\d|,|\s*Ratings)", full_text)
                    if m:
                        rating = m.group(1)

                    # ---- total reviews ---- e.g. "3,340" from "3,340 Reviews"
                    total_reviews = "N/A"
                    m = re.search(r"(\d+(?:,\d+)*)\s+Reviews", full_text)
                    if m:
                        total_reviews = m.group(1)

                    # ---- product link / id ----
                    link_el = item.find_element(By.CSS_SELECTOR, "a[href*='/p/']")
                    href = link_el.get_attribute("href")
                    product_link = href if href.startswith("http") else "https://www.flipkart.com" + href
                    m = re.findall(r"/p/(itm[0-9A-Za-z]+)", href)
                    product_id = m[0] if m else "N/A"

                    top_reviews = self.get_top_reviews(product_link, count=review_count)
                    products.append([product_id, title, rating, total_reviews, price, top_reviews])

                except Exception as e:
                    print(f"Error occurred while processing item: {e}")
                    continue

            return products
        finally:
            driver.quit()

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
            writer.writerow(["product_id", "product_title", "rating", "total_reviews", "price", "top_reviews"])
            writer.writerows(data)


if __name__ == "__main__":
    scraper = FlipkartScraper()
    products = scraper.scrape_flipkart_products("Samsung s24", max_products=2, review_count=3)
    scraper.save_to_csv(products, "data/product_reviews_new.csv")