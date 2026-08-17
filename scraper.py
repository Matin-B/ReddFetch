import asyncio
import os
import re
import sys
import argparse
from urllib.parse import urlparse
from playwright.async_api import async_playwright

def get_reddit_url() -> str:
    """
    Parse command-line arguments to get the Reddit URL.
    If no argument is provided, prompt the user via interactive input.
    """
    parser = argparse.ArgumentParser(description="Reddit Image Scraper and Downloader")
    parser.add_argument(
        "url", 
        nargs="?", 
        help="The Reddit post URL (supports both standard and short /s/ links)"
    )
    args = parser.parse_args()

    user_url = args.url
    if not user_url:
        print("📥 Please enter the Reddit post URL:")
        user_url = input("> ").strip()
        
    if not user_url:
        print("❌ Error: No URL provided. Exiting.")
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

def extract_subfolder_name(image_urls: list) -> str:
    """
    Extract the post slug from the first valid preview.redd.it image URL
    using Regular Expressions to create a clean subfolder name.
    """
    for url in image_urls:
        parsed_url = urlparse(url)
        match = re.search(r"/([^/]+)-v\d+-", parsed_url.path)
        if match:
            return match.group(1)
            
    return "unknown_reddit_post"

async def extract_and_download_preview_images(original_url: str):
    """
    Resolve short URLs, navigate to the dynamically generated Reddit embed URL, 
    extract the post title, fetch the fully rendered HTML source safely, 
    filter main images, and download them. Includes WAF evasion techniques.
    """
    base_download_dir = "downloads"
    
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
        
        # NEW: URL Resolution Phase
        # Send a safe request through the spoofed context to follow redirects
        # This expands short links (e.g., /s/...) into standard canonical paths
        print(f"\n🔍 Resolving original URL (following redirects): {original_url}")
        try:
            resolve_response = await context.request.get(original_url)
            resolved_url = resolve_response.url
            print(f"🔗 Final Resolved URL: {resolved_url}")
        except Exception as e:
            print(f"❌ Failed to resolve URL: {e}")
            await browser.close()
            return
            
        # Format the embed URL using the fully resolved link
        embed_url = format_embed_url(resolved_url)
        
        page = await context.new_page()
        
        print(f"🚀 Navigating to properly formatted Embed URL: {embed_url}")
        await page.goto(embed_url, wait_until="networkidle")
        
        try:
            reddit_frame = page.frame_locator("iframe").first
            
            # Wait for the first image to render in the DOM
            await reddit_frame.locator("img").first.wait_for(state="attached")
            
            # Extract the fully rendered HTML source code of the iframe
            frame_html_content = await reddit_frame.locator("html").evaluate(
                "node => node.outerHTML"
            )
            
            title_locator = reddit_frame.locator("h1")
            if await title_locator.count() > 0:
                post_title = await title_locator.first.inner_text()
                print(f"📄 Post Title Extracted: {post_title}")
            else:
                print("⚠️ Could not locate the post title <h1> tag.")
            
            image_elements = await reddit_frame.locator("img").all()
            image_urls = []
            
            for img in image_elements:
                src = await img.get_attribute("src")
                if src:
                    parsed_src = urlparse(src)
                    if parsed_src.netloc == "preview.redd.it":
                        if src not in image_urls:
                            image_urls.append(src)
            
            if not image_urls:
                print("\n[-] 📭 No images from 'preview.redd.it' were found.")
                return

            print(f"\n[+] 🎉 Success! {len(image_urls)} target URLs extracted.")
            
            subfolder_name = extract_subfolder_name(image_urls)
            final_download_path = os.path.join(base_download_dir, subfolder_name)
            
            os.makedirs(final_download_path, exist_ok=True)
            print(f"📁 Target Directory Created: {final_download_path}\n")
            
            # Write the extracted HTML content to a file
            html_filepath = os.path.join(final_download_path, "rendered_source.html")
            with open(html_filepath, "w", encoding="utf-8") as file:
                file.write(frame_html_content)
            print(f"🌐 Rendered HTML source saved to: {html_filepath}")
            
            for url in image_urls:
                print(f"⏳ Downloading: {url}")
                
                image_response = await context.request.get(
                    url,
                    headers={
                        "Referer": embed_url,
                        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8"
                    }
                )
                
                if image_response.status == 200:
                    parsed_url = urlparse(url)
                    filename = os.path.basename(parsed_url.path)
                    
                    if not filename:
                        filename = f"image_{image_urls.index(url)}.jpg"
                        
                    filepath = os.path.join(final_download_path, filename)
                    image_data = await image_response.body()
                    
                    with open(filepath, "wb") as f:
                        f.write(image_data)
                        
                    print(f"    ✅ Saved to: {filepath}")
                else:
                    print(f"    ❌ Failed! HTTP Status: {image_response.status}")
                
        except Exception as e:
            print(f"\n[!] 🚨 An error occurred during extraction/download: {e}")
            
        finally:
            await browser.close()

if __name__ == "__main__":
    target_reddit_url = get_reddit_url()
    asyncio.run(extract_and_download_preview_images(target_reddit_url))