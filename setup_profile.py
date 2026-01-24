import asyncio
from playwright.async_api import async_playwright
import os

USER_DATA_DIR = "./browser_profile"
URL = "https://www.cardmarket.com/en/Riftbound/Products/Booster-Boxes/Origins-Booster-Box"

async def setup():
    print(f"Creating persistent profile in '{USER_DATA_DIR}'...")
    if not os.path.exists(USER_DATA_DIR):
        os.makedirs(USER_DATA_DIR)

    async with async_playwright() as p:
        # Back to Firefox, but with specific anti-detection prefs
        print("Launching Firefox (Custom Prefs)...")
        context = await p.firefox.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            user_agent="Mozilla/5.0 (X11; Linux x86_64; rv:147.0) Gecko/20100101 Firefox/147.0",
            viewport={"width": 1280, "height": 720},
            firefox_user_prefs={
                "dom.webdriver.enabled": False,
                "useAutomationExtension": False,
            }
        )
        
        page = context.pages[0]
        # No external stealth, relying on prefs
        
        print(f"Navigating to {URL}...")
        await page.goto(URL)
        
        print("-------------------------------------------------")
        print("PLEASE INTERACT WITH THE BROWSER WINDOW NOW.")
        print("1. Solve the 'Just a moment' check.")
        print("2. Ensure you can see the product page.")
        print("-------------------------------------------------")
        input("Press ENTER here when the page is loaded correctly: ")
        
        # We don't need to manually save cookies; persistent context does it automatically.
        await context.close()
        print("Profile saved. You can now run the import script.")

if __name__ == "__main__":
    asyncio.run(setup())
