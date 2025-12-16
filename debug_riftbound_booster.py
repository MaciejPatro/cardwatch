import asyncio
from playwright.async_api import async_playwright
from playwright_stealth.stealth import Stealth
from bs4 import BeautifulSoup
from cookie_loader import parse_netscape_cookies

URL = "https://www.cardmarket.com/en/Riftbound/Products/Booster-Boxes/Origins-Booster-Box"

async def debug():
    async with async_playwright() as p:
        # Try headful mode to see if it bypasses
        browser = await p.firefox.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64; rv:146.0) Gecko/20100101 Firefox/146.0",
            extra_http_headers={"Referer": "https://www.cardmarket.com/"}
        )
        
        # Load Cookies
        try:
            cookies = parse_netscape_cookies("cookies-cardmarket-com.txt")
            # Manually inject the provided cf_clearance
            cf_clearance = {
                "name": "cf_clearance",
                "value": "h2wrFuqEEa.5iDLkOpZPs8DAVlo5qRcvbBQ1iSyrFoQ-1765547636-1.2.1.1-Q4t2zwopbqf5jblLRLdH4uC.LjH.YpEIk4uXEfb8arzACQ9WXTQHfB39zUnjOZDJrA6CZ1PXu_WRVTKxrehSCzrxwjgSV1XziLqbBxFyhTJ9SW0Ic2IrT5Vng9QpU7ZztKPdvGwat9PjegGaePjTRDq30uhQuYc6O1UM_BrC5iqPMQ7UoobQegRUH4XxVnP6hTXPBsN.txeH35bs5hCyLAQ5wSgzlCayi4MU3uE_obg",
                "domain": ".cardmarket.com",
                "path": "/",
                "secure": True
            }
            cookies.append(cf_clearance)
            
            await context.add_cookies(cookies)
            print(f"Loaded {len(cookies)} cookies (including manual cf_clearance).")
        except Exception as e:
            print(f"Failed to load cookies: {e}")

        page = await context.new_page()
        await Stealth().apply_stealth_async(page)
        print(f"Navigating to {URL}...")
        await page.goto(URL)
        content = await page.content()
        
        soup = BeautifulSoup(content, 'html.parser')
        h1 = soup.find('h1')
        print(f"H1: {h1}")
        if h1:
            print(f"H1 Text: {h1.get_text(strip=True)}")
            
        img = soup.select_one('div.tab-content img')
        print(f"Tab Image: {img}")
        
        img2 = soup.select_one('div.image img')
        print(f"Div Image: {img2}")

        await page.screenshot(path="debug_booster.png")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(debug())
