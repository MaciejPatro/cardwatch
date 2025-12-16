import asyncio
from playwright.async_api import async_playwright
from playwright_stealth.stealth import Stealth
import json

URL = "https://www.cardmarket.com/en/Riftbound/Products/Booster-Boxes/Origins-Booster-Box"

async def harvest():
    async with async_playwright() as p:
        # Try Firefox which might trigger different anti-bot checks
        browser = await p.firefox.launch(headless=False)
        context = await browser.new_context()
        
        page = await context.new_page()
        # await Stealth().apply_stealth_async(page) # Disabled to test raw Firefox
        
        print(f"Opening {URL}...")
        await page.goto(URL)
        
        print("-------------------------------------------------")
        print("PLEASE INTERACT WITH THE BROWSER WINDOW NOW.")
        print("Solve the captcha / 'Just a moment' check.")
        print("Once you are on the actual product page, return here.")
        input("Press ENTER in this terminal to save cookies and close: ")
        print("-------------------------------------------------")
        
        cookies = await context.cookies()
        with open("cookies-cardmarket-com.txt", "w") as f:
            # Write in Netscape format (simplified) or just JSON
            # Let's verify what the loader expects. 
            # The loader expects Netscape. 
            # For simplicity, let's just save as JSON and I'll update the loader to handle JSON too,
            # OR write Netscape format here.
            
            f.write("# Netscape HTTP Cookie File\n\n")
            for c in cookies:
                domain = c['domain']
                flag = 'TRUE' if domain.startswith('.') else 'FALSE'
                path = c['path']
                secure = 'TRUE' if c['secure'] else 'FALSE'
                expiration = int(c['expires']) if 'expires' in c else 0
                name = c['name']
                value = c['value']
                f.write(f"{domain}\t{flag}\t{path}\t{secure}\t{expiration}\t{name}\t{value}\n")
        
        print("Cookies saved to cookies-cardmarket-com.txt")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(harvest())
