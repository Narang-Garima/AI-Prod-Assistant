# src/prod_assistant/etl/data_scrapper.py
# Run:
#   uv run --active python src/prod_assistant/etl/data_scrapper.py

import csv
import os
import re
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from bs4 import BeautifulSoup
import undetected_chromedriver as uc

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ----------------- Helpers: parsing -----------------

def _first_text(soup: BeautifulSoup, selectors: List[str]) -> str:
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            txt = el.get_text(" ", strip=True)
            if txt:
                return txt
    return "N/A"


def _first_attr(soup: BeautifulSoup, selectors: List[str], attr: str) -> Optional[str]:
    for sel in selectors:
        el = soup.select_one(sel)
        if el and el.has_attr(attr):
            val = el.get(attr)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def _normalize_flipkart_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return "https://www.flipkart.com" + href
    return "https://www.flipkart.com/" + href


def _extract_ids_from_href(href: str) -> Tuple[str, str]:
    """
    Returns (pid, itm_id).
    pid is in query: pid=XXXX
    itm_id sometimes in /p/itm....
    """
    itm_id = "N/A"
    pid = "N/A"

    if href:
        m_itm = re.search(r"/p/(itm[0-9A-Za-z]+)", href)
        if m_itm:
            itm_id = m_itm.group(1)

        m_pid = re.search(r"[?&]pid=([A-Z0-9]+)", href)
        if m_pid:
            pid = m_pid.group(1)

    return pid, itm_id


def _extract_total_reviews_from_count(text: str) -> str:
    if not text or text == "N/A":
        return "N/A"
    m = re.search(r"(\d[\d,]*)", text)
    return m.group(1) if m else "N/A"


def _looks_like_flipkart_soft_404(html: str) -> bool:
    t = (html or "").lower()
    return ("moved or deleted" in t) or ("go to homepage" in t) or ("page you are looking for" in t)


# ----------------- Browser helpers -----------------

def _make_driver(version_main: int = 145, headless: bool = False) -> uc.Chrome:
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    # options.add_argument("--disable-gpu")  # optional
    if headless:
        options.add_argument("--headless=new")
    return uc.Chrome(options=options, version_main=version_main, use_subprocess=True)


def _close_popups(driver, timeout: float = 2.0) -> None:
    candidates = [
        (By.CSS_SELECTOR, "button._2KpZ6l._2doB4z"),
        (By.CSS_SELECTOR, "button[aria-label='Close']"),
        (By.CSS_SELECTOR, "span._30XB9F"),
        (By.XPATH, "//button[contains(., '✕')]"),
        (By.XPATH, "//span[contains(., '✕')]"),
    ]
    end = time.time() + timeout
    while time.time() < end:
        closed = False
        for by, sel in candidates:
            try:
                el = WebDriverWait(driver, 0.25).until(EC.presence_of_element_located((by, sel)))
                try:
                    el.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", el)
                time.sleep(0.15)
                closed = True
            except Exception:
                pass
        if not closed:
            break


# ----------------- Review extraction (robust) -----------------

BUYER_ANCHORS = [
    "Verified Buyer",
    "Certified Buyer",
    "Gold Reviewer",
    "Silver Reviewer",
    "Bronze Reviewer",
]

def _extract_review_cards_from_html(html: str) -> List[str]:
    """
    Find review-like blocks by anchoring on buyer labels
    so it works for phones (Certified Buyer) + other products (Verified Buyer).
    """
    soup = BeautifulSoup(html, "html.parser")
    cards: List[str] = []
    seen = set()

    pattern = re.compile("|".join(re.escape(x) for x in BUYER_ANCHORS), re.IGNORECASE)
    nodes = soup.find_all(string=pattern)

    for n in nodes:
        parent = n.parent
        if not parent:
            continue

        container = parent
        best = None

        for _ in range(14):
            if not container or not getattr(container, "parent", None):
                break
            container = container.parent

            txt = container.get_text(" ", strip=True)
            txt = re.sub(r"\s+", " ", txt).strip()

            if any(a.lower() in txt.lower() for a in BUYER_ANCHORS) and (120 <= len(txt) <= 1600):
                if re.search(r"\b(year|month|day)s?\s+ago\b", txt, flags=re.IGNORECASE):
                    best = txt
                    break
                if best is None:
                    best = txt

        if best and best not in seen:
            seen.add(best)
            cards.append(best)

    return cards


def clean_review_card_text(card: str) -> str:
    """
    Heuristic cleanup to keep only review message-like text.
    Removes rating summaries, UI words, buyer tags, dates, vote counts.
    """
    t = re.sub(r"\s+", " ", (card or "")).strip()

    # remove header summary like "4.6 Excellent based on..."
    t = re.sub(r"^\d+(\.\d+)?\s+\w+\s+based on.*?(Verified|Certified)\s+Buyers?\s*", "", t, flags=re.IGNORECASE)

    # remove UI words
    t = re.sub(r"\bShow all reviews\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\bRead more\b|\bmore\b", "", t, flags=re.IGNORECASE)

    # remove buyer tags
    t = re.sub(r"\b(Verified|Certified)\s+Buyer\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\b(Gold|Silver|Bronze)\s+Reviewer\b", "", t, flags=re.IGNORECASE)

    # remove "1 month ago"
    t = re.sub(r"\b\d+\s+(day|month|year)s?\s+ago\b", "", t, flags=re.IGNORECASE)

    # remove vote counts like "230 67"
    t = re.sub(r"\b\d+\s+\d+\b", "", t)

    # remove rating label at start
    t = re.sub(
        r"^\s*\d+\s*(Fabulous!|Excellent|Brilliant|Must buy!|Great|Good|Very Good|Average|Poor|Terrible)\s*",
        "",
        t,
        flags=re.IGNORECASE
    )

    t = re.sub(r"\s+", " ", t).strip()

    # filter Q&A noise (common on phone pages)
    if re.search(r"\b(does this|is this|can i|how much|what is)\b", t, flags=re.IGNORECASE):
        # don’t fully drop if it also contains clear review sentiment, but generally Q&A is noise
        if len(t) < 120:
            return ""

    return t if len(t) >= 20 else ""


def _try_click_show_all_reviews(driver) -> bool:
    xpaths = [
        "//*[self::span or self::a or self::button or self::div][contains(., 'Show all reviews')]",
        "//*[contains(., 'Show all reviews')]",
        "//*[self::span or self::a or self::button or self::div][contains(., 'All reviews')]",
    ]
    for xp in xpaths:
        try:
            el = WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.XPATH, xp)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(0.25)
            driver.execute_script("arguments[0].click();", el)
            return True
        except Exception:
            pass
    return False


# ----------------- Data model -----------------

@dataclass
class ProductRow:
    product_id: str
    product_title: str
    rating: str
    total_reviews: str
    price: str
    top_reviews: str


# ----------------- Scraper -----------------

class FlipkartScraper:
    def __init__(self, output_dir: str = "data", chrome_version_main: int = 145, headless: bool = False):
        self.output_dir = output_dir
        self.chrome_version_main = chrome_version_main
        self.headless = headless
        os.makedirs(self.output_dir, exist_ok=True)

    def _get_reviews(self, driver, product_url: str, total_needed: int = 50) -> List[str]:
        """
        Strategy:
        1) Try /product-reviews/{itm}?pid={pid}
           - If it is soft-404 / moved-deleted OR no anchors -> fallback
        2) Fallback to product page -> scroll and extract
        """
        pid, itm_id = _extract_ids_from_href(product_url)

        # ---- 1) Try review page route ----
        if itm_id != "N/A" and pid != "N/A":
            review_url = f"https://www.flipkart.com/product-reviews/{itm_id}?pid={pid}"
            driver.get(review_url)
            WebDriverWait(driver, 20).until(lambda d: d.execute_script("return document.readyState") == "complete")
            _close_popups(driver)

            html = driver.page_source
            if not _looks_like_flipkart_soft_404(html):
                cards = _extract_review_cards_from_html(html)
                cleaned = []
                seen = set()
                for c in cards:
                    t = clean_review_card_text(c)
                    if t and t not in seen:
                        seen.add(t)
                        cleaned.append(t)
                    if len(cleaned) >= total_needed:
                        return cleaned[:total_needed]

                # scroll a bit on review page
                for _ in range(10):
                    driver.execute_script("window.scrollBy(0,1400)")
                    time.sleep(0.6)
                    cards = _extract_review_cards_from_html(driver.page_source)
                    for c in cards:
                        t = clean_review_card_text(c)
                        if t and t not in seen:
                            seen.add(t)
                            cleaned.append(t)
                        if len(cleaned) >= total_needed:
                            return cleaned[:total_needed]

                if cleaned:
                    return cleaned[:total_needed]

        # ---- 2) Fallback: product page ----
        driver.get(product_url)
        WebDriverWait(driver, 25).until(lambda d: d.execute_script("return document.readyState") == "complete")
        _close_popups(driver)

        # scroll toward reviews
        for _ in range(6):
            driver.execute_script("window.scrollBy(0, 900);")
            time.sleep(0.55)

        _try_click_show_all_reviews(driver)
        time.sleep(1.0)

        reviews: List[str] = []
        seen = set()

        for _ in range(18):
            cards = _extract_review_cards_from_html(driver.page_source)
            for c in cards:
                t = clean_review_card_text(c)
                if t and t not in seen:
                    seen.add(t)
                    reviews.append(t)
                    if len(reviews) >= total_needed:
                        return reviews[:total_needed]

            driver.execute_script("window.scrollBy(0, 1400);")
            time.sleep(0.7)

        return reviews[:total_needed]

    def scrape_flipkart_products(self, query: str, max_products: int = 1, review_count: int = 2) -> List[List[str]]:
        """
        Backward-compatible for your Streamlit:
        - max_products: products per query
        - review_count: how many reviews saved in CSV (1..50)
        """
        review_count = max(1, min(int(review_count), 50))

        search_driver = _make_driver(self.chrome_version_main, headless=self.headless)
        review_driver = _make_driver(self.chrome_version_main, headless=self.headless)  # reused

        products: List[ProductRow] = []
        try:
            search_url = f"https://www.flipkart.com/search?q={query.replace(' ', '+')}"
            search_driver.get(search_url)

            WebDriverWait(search_driver, 25).until(lambda d: d.execute_script("return document.readyState") == "complete")
            _close_popups(search_driver)

            WebDriverWait(search_driver, 25).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-id], a[href]"))
            )

            # load a bit more
            for _ in range(2):
                ActionChains(search_driver).send_keys(Keys.END).perform()
                time.sleep(0.75)

            cards = search_driver.find_elements(By.CSS_SELECTOR, "div[data-id]")
            if not cards:
                # fallback if flipkart changes structure
                cards = search_driver.find_elements(By.CSS_SELECTOR, "a[href*='/p/']")

            for el in cards[: max_products * 8]:
                if len(products) >= max_products:
                    break

                html = el.get_attribute("outerHTML") or ""
                soup = BeautifulSoup(html, "html.parser")

                # title: add more fallbacks (phones often differ)
                title = _first_text(soup, [
                    "a.pIpigb",
                    "div.KzDlHZ",
                    "div._4rR01T",
                    "a[title]",
                    "img[alt]",         # last resort
                ])
                # prefer attribute title if present
                title_attr = _first_attr(soup, ["a[title]"], "title")
                if title_attr:
                    title = title_attr.strip()

                # if still N/A try image alt
                if title == "N/A":
                    alt = _first_attr(soup, ["img[alt]"], "alt")
                    if alt:
                        title = alt.strip()

                price = _first_text(soup, [
                    "div.hZ3P6w",
                    "div.Nx9bqj",
                    "div._30jeq3",
                    "div._1_WHN1",
                ])

                rating = _first_text(soup, [
                    "div.MKiFS6",
                    "div.XQDdHH",
                    "div._3LWZlK",
                ])
                m = re.search(r"(\d+(\.\d+)?)", rating)
                rating = m.group(1) if m else rating

                rating_count = _first_text(soup, [
                    "span.PvbNMB",
                    "span.Wphh3N",
                    "span._2_R_DZ",
                ])
                total_reviews = _extract_total_reviews_from_count(rating_count)

                href = _first_attr(soup, [
                    "a.pIpigb[href]",
                    "a.GnxRXv[href]",
                    "a[href*='/p/']",
                    "a[href]",
                ], "href")

                if price == "N/A" or not href:
                    continue

                product_link = _normalize_flipkart_url(href)
                pid, itm_id = _extract_ids_from_href(href)

                # reviews: fetch up to 50, store only review_count
                all_reviews = self._get_reviews(review_driver, product_link, total_needed=50)
                selected = all_reviews[:review_count]
                top_reviews = " || ".join(selected) if selected else "No reviews found"

                # product_id: prefer pid, else itm_id, else data-id (if exists)
                product_id = pid if pid != "N/A" else (itm_id if itm_id != "N/A" else "N/A")

                products.append(ProductRow(
                    product_id=product_id,
                    product_title=title,
                    rating=rating if rating else "N/A",
                    total_reviews=total_reviews,
                    price=price,
                    top_reviews=top_reviews,
                ))

            return [[p.product_id, p.product_title, p.rating, p.total_reviews, p.price, p.top_reviews] for p in products]

        finally:
            try:
                search_driver.quit()
            except Exception:
                pass
            try:
                review_driver.quit()
            except Exception:
                pass

    def save_to_csv(self, data: List[List[str]], filename: str = "data/product_reviews.csv") -> str:
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

        return path


if __name__ == "__main__":
    scraper = FlipkartScraper(output_dir="data", chrome_version_main=145, headless=False)
    rows = scraper.scrape_flipkart_products("gaming laptop", max_products=4, review_count=5)
    out = scraper.save_to_csv(rows, "data/product_reviews.csv")
    print("Saved:", out)
    print("Rows scraped:", len(rows))