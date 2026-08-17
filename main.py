import argparse
import asyncio
import logging
import os
import sys
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

LOG_FILE = "reddit_scraper.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def get_reddit_url() -> str:
    """
    Parse command-line arguments to get the Reddit URL.
    If no argument is provided, prompt the user via interactive input.
    """
    parser = argparse.ArgumentParser(description="Reddit HTML Source Scraper")
    parser.add_argument(
        "url", 
        nargs="?", 
        help="The Reddit post URL (supports both standard and short /s/ links)"
    )
    args = parser.parse_args()

    user_url = args.url
    if not user_url:
        logger.info("📥 Please enter the Reddit post URL:")
        user_url = input("> ").strip()
        
    if not user_url:
        logger.error("❌ Error: No URL provided. Exiting.")
        sys.exit(1)
        
    return user_url

def format_embed_url(raw_url: str) -> str:
    """
    Transforms a fully resolved Reddit URL into a valid Embed URL.
    Maps original query parameters using '&' to maintain NSFW bypass tokens.
    """
    parsed_url = urlparse(raw_url)
    clean_path = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
    
    if parsed_url.query:
        return f"https://publish.reddit.com/embed?url={clean_path}&{parsed_url.query}"
    
    return f"https://publish.reddit.com/embed?url={clean_path}"

async def extract_reddit_html(original_url: str):
    """
    Resolve short URLs, navigate to the dynamically generated Reddit embed URL, 
    and extract the fully rendered HTML source of the iframe without downloading media.
    """
    base_download_dir = "downloads"
    os.makedirs(base_download_dir, exist_ok=True)
    
    real_user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        context = await browser.new_context(
            user_agent=real_user_agent,
            viewport={"width": 1920, "height": 1080}
        )
        
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        
        # URL Resolution Phase (Kept exactly as requested)
        logger.info(f"\n🔍 Resolving original URL (following redirects): {original_url}")
        try:
            resolve_response = await context.request.get(original_url)
            resolved_url = resolve_response.url
            logger.info(f"🔗 Final Resolved URL: {resolved_url}")
        except Exception as e:
            logger.error(f"❌ Failed to resolve URL: {e}")
            await browser.close()
            return
            
        embed_url = format_embed_url(resolved_url)
        
        page = await context.new_page()
        
        logger.info(f"🚀 Navigating to properly formatted Embed URL: {embed_url}")
        await page.goto(embed_url, wait_until="networkidle")
        
        try:
            reddit_frame = page.frame_locator("iframe").first
            
            # Wait for the iframe's body to attach to ensure DOM is fully loaded
            await reddit_frame.locator("body").wait_for(state="attached")
            
            # Extract the fully rendered HTML source code of the iframe
            frame_html_content = await reddit_frame.locator("html").evaluate(
                "node => node.outerHTML"
            )
            logger.info(f"\n[+] ✅ HTML content extracted using Playwright successfully.")

            soup = BeautifulSoup(frame_html_content, "html.parser")
            post_title = soup.find("h1").text
    
            post_upvotes = None
            target_span = soup.find(
                lambda tag: tag.name == "span" and "upvotes" in tag.get_text()
            )
            if target_span:
                post_upvotes = target_span.find("faceplate-number").get("number")

            image_urls = []
            for img in soup.find_all("faceplate-img"):
                img_url = img.get("src").split("?")[0]
                image_urls.append(img_url)
                
        except Exception as e:
            logger.error(f"\n[!] 🚨 An error occurred during HTML extraction: {e}")
            
        finally:
            await browser.close()


if __name__ == "__main__":
    target_reddit_url = get_reddit_url()
    asyncio.run(extract_reddit_html(target_reddit_url))
