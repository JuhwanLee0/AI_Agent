import os
import json
import logging
from typing import Dict, Any, Optional, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PlaywrightBrowser")

# 저사양 VM (1GB RAM + 2GB Swap) 친화적 브라우저 기본 아규먼트
CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--disable-extensions",
    "--no-zygote",
    "--single-process",
]

class PlaywrightBrowser:
    """
    Playwright 기반 초경량 웹 브라우징 & 스크래핑 & 스크린샷 제어 도구
    - GCP 저사양 인프라(2GB Swap) 메모리 누수 방지 설계
    - 모든 세션 작업 후 브라우저 및 컨텍스트 즉시 close 처리
    """
    def __init__(self, headless: bool = True, timeout_ms: int = 20000):
        self.headless = headless
        self.timeout_ms = timeout_ms

    def is_available(self) -> bool:
        """Playwright 라이브러리 설치 여부 점검"""
        try:
            import playwright
            return True
        except ImportError:
            return False

    def fetch_page_text(self, url: str, wait_selector: Optional[str] = None) -> Dict[str, Any]:
        """
        웹페이지를 방문하여 텍스트 및 기본 메타데이터(제목, 설명) 추출
        """
        if not self.is_available():
            return {
                "success": False,
                "error": "playwright 패키지가 설치되지 않았습니다. `pip install playwright && playwright install chromium`을 실행하세요.",
                "url": url
            }

        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=self.headless,
                    args=CHROMIUM_ARGS
                )
                context = None
                try:
                    context = browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    )
                    page = context.new_page()
                    page.set_default_timeout(self.timeout_ms)

                    logger.info(f"[Playwright] Navigating to: {url}")
                    page.goto(url, wait_until="domcontentloaded")

                    if wait_selector:
                        try:
                            page.wait_for_selector(wait_selector, timeout=5000)
                        except Exception:
                            logger.warning(f"[Playwright] Timeout waiting for selector: {wait_selector}")

                    title = page.title()
                    # 불필요한 스크립트/스타일 태그 제거 후 텍스트 추출
                    body_text = page.inner_text("body")
                    clean_text = "\n".join([line.strip() for line in body_text.splitlines() if line.strip()])

                    return {
                        "success": True,
                        "url": url,
                        "title": title,
                        "text": clean_text[:4000],  # LLM 컨텍스트 한도 고려 4000자 제한
                        "length": len(clean_text)
                    }
                finally:
                    if context:
                        context.close()
                    browser.close()
        except Exception as e:
            logger.error(f"[Playwright] fetch_page_text error: {e}")
            return {
                "success": False,
                "url": url,
                "error": str(e)
            }

    def take_screenshot(self, url: str, output_path: str = "output/screenshot.png", full_page: bool = False) -> Dict[str, Any]:
        """
        웹페이지 스크린샷 캡처 및 이미지 파일 저장
        """
        if not self.is_available():
            return {
                "success": False,
                "error": "playwright 패키지가 설치되지 않았습니다.",
                "url": url
            }

        try:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=self.headless,
                    args=CHROMIUM_ARGS
                )
                context = None
                try:
                    context = browser.new_context(viewport={"width": 1280, "height": 800})
                    page = context.new_page()
                    page.set_default_timeout(self.timeout_ms)

                    logger.info(f"[Playwright] Capturing screenshot: {url} -> {output_path}")
                    try:
                        page.goto(url, wait_until="networkidle")
                    except Exception:
                        logger.warning(f"[Playwright] networkidle timeout, falling back to load event")
                        page.goto(url, wait_until="load")
                    page.screenshot(path=output_path, full_page=full_page)

                    return {
                        "success": True,
                        "url": url,
                        "output_path": output_path,
                        "file_size": os.path.getsize(output_path)
                    }
                finally:
                    if context:
                        context.close()
                    browser.close()
        except Exception as e:
            logger.error(f"[Playwright] take_screenshot error: {e}")
            return {
                "success": False,
                "url": url,
                "error": str(e)
            }

    def search_duckduckgo(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """
        DuckDuckGo 검색 결과 스크래핑 (API 키 없이 웹 검색 수행)
        """
        if not self.is_available():
            return [{"title": "오류", "link": "", "snippet": "Playwright가 설치되지 않았습니다."}]

        results = []
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless, args=CHROMIUM_ARGS)
                context = browser.new_context()
                page = context.new_page()
                page.set_default_timeout(self.timeout_ms)

                search_url = f"https://html.duckduckgo.com/html/?q={requests_quote(query)}"
                page.goto(search_url, wait_until="domcontentloaded")

                elements = page.query_selector_all(".result")
                for el in elements[:max_results]:
                    title_el = el.query_selector(".result__title")
                    snippet_el = el.query_selector(".result__snippet")
                    url_el = el.query_selector(".result__url")

                    title = title_el.inner_text().strip() if title_el else ""
                    snippet = snippet_el.inner_text().strip() if snippet_el else ""
                    link = url_el.inner_text().strip() if url_el else ""

                    if title:
                        results.append({
                            "title": title,
                            "snippet": snippet,
                            "link": link
                        })

                context.close()
                browser.close()
        except Exception as e:
            logger.error(f"[Playwright] search error: {e}")
            results.append({"title": "검색 오류", "link": "", "snippet": str(e)})

        return results

def requests_quote(text: str) -> str:
    import urllib.parse
    return urllib.parse.quote_plus(text)


if __name__ == "__main__":
    browser = PlaywrightBrowser()
    print("Playwright Available:", browser.is_available())
