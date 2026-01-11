import asyncio
from playwright.async_api import async_playwright
from cookie_loader import parse_netscape_cookies
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

URL = "https://www.cardmarket.com/en/OnePiece/Products/Boosters/Romance-Dawn-Booster"

async def debug_scrape():
    cookies = []
    try:
        cookies = parse_netscape_cookies("cookies-cardmarket-com.txt")
        cf_clearance = {
            "name": "cf_clearance",
            "value": "h2wrFuqEEa.5iDLkOpZPs8DAVlo5qRcvbBQ1iSyrFoQ-1765547636-1.2.1.1-Q4t2zwopbqf5jblLRLdH4uC.LjH.YpEIk4uXEfb8arzACQ9WXTQHfB39zUnjOZDJrA6CZ1PXu_WRVTKxrehSCzrxwjgSV1XziLqbBxFyhTJ9SW0Ic2IrT5Vng9QpU7ZztKPdvGwat9PjegGaePjTRDq30uhQuYc6O1UM_BrC5iqPMQ7UoobQegRUH4XxVnP6hTXPBsN.txeH35bs5hCyLAQ5wSgzlCayi4MU3uE_obg",
            "domain": ".cardmarket.com",
            "path": "/",
            "secure": True
        }
        cookies.append(cf_clearance)
    except Exception as e:
        logger.error(f"Failed to load cookies: {e}")

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64; rv:146.0) Gecko/20100101 Firefox/146.0",
            extra_http_headers={"Referer": "https://www.cardmarket.com/"}
        )
        if cookies:
            await context.add_cookies(cookies)

        logger.info(f"Navigating to {URL}")
        page = await context.new_page()
        await page.goto(URL, wait_until="networkidle")
        
        # Wait for potential Cloudflare challenge
        logger.info("Waiting 5 seconds for challenges...")
        await asyncio.sleep(5)
        
        title = await page.title()
        logger.info(f"Page title: {title}")
        
        await page.screenshot(path="debug_screenshot.png")
        logger.info("Saved screenshot to debug_screenshot.png")
        
        content = await page.content()
        with open("debug_output.html", "w") as f:
            f.write(content)
        logger.info("Saved HTML to debug_output.html")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(debug_scrape())
