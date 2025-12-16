import requests
import os

PROXY_SOURCES = [
    {
        "url": "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/https/data.txt",
        "prefix": "http://"  # These are HTTP proxies that support CONNECT (HTTPS tunneling)
    },
    {
        "url": "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks4/data.txt",
        "prefix": "socks4://"
    },
    {
        "url": "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks5/data.txt",
        "prefix": "socks5://"
    }
]
OUTPUT_FILE = "proxies.txt"

def fetch_proxies():
    all_proxies = []
    
    for source in PROXY_SOURCES:
        url = source["url"]
        prefix = source["prefix"]
        print(f"Fetching proxies from {url}...")
        
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            lines = response.text.strip().splitlines()
            print(f"Found {len(lines)} proxies from {url}.")
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                # If the line already has a protocol, don't double add, but these raw lists usually don't
                if "://" not in line:
                    all_proxies.append(f"{prefix}{line}")
                else:
                    all_proxies.append(line)

        except Exception as e:
            print(f"Error fetching from {url}: {e}")

    if not all_proxies:
        print("No proxies found from any source.")
        return

    # Deduplicate while preserving order
    unique_proxies = list(dict.fromkeys(all_proxies))

    with open(OUTPUT_FILE, "w") as f:
        f.write("# Automatically fetched from proxifly/free-proxy-list\n")
        f.write("# Includes HTTPS, SOCKS4, and SOCKS5 proxies\n")
        for proxy in unique_proxies:
            f.write(f"{proxy}\n")
    
    print(f"Successfully wrote {len(unique_proxies)} proxies to {OUTPUT_FILE}")

if __name__ == "__main__":
    fetch_proxies()
