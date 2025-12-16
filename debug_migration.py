import asyncio
from playwright.async_api import async_playwright

async def debug():
    url = "https://www.cardmarket.com/OnePiece/Products?idProduct=750707"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print(f"Navigating to {url}...")
        response = await page.goto(url, wait_until="domcontentloaded")
        print(f"Final URL: {page.url}")
        print(f"Response URL: {response.url}")
        print(f"Status: {response.status}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(debug())
