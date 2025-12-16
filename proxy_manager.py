import random
import os
import logging

logger = logging.getLogger(__name__)

class ProxyManager:
    def __init__(self, proxy_file="proxies.txt"):
        self.proxy_file = proxy_file
        self.proxies = []
        self.current_index = 0
        self.load_proxies()

    def load_proxies(self):
        if not os.path.exists(self.proxy_file):
            return
        
        with open(self.proxy_file, "r") as f:
            lines = f.readlines()
        
        valid_proxies = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            valid_proxies.append(self._parse_proxy(line))
        
        self.proxies = valid_proxies
        # Shuffle to start random
        if self.proxies:
            random.shuffle(self.proxies)

    def _parse_proxy(self, proxy_str):
        # Allow format: ip:port or ip:port:user:pass
        # Playwright expects: { "server": "...", "username": "...", "password": "..." }
        
        if "://" in proxy_str:
            # Assume it's a full URL, return directly as server
            return {"server": proxy_str}

        parts = proxy_str.split(":")
        if len(parts) == 2:
            return {"server": f"http://{parts[0]}:{parts[1]}"}
        elif len(parts) == 4:
            return {
                "server": f"http://{parts[0]}:{parts[1]}",
                "username": parts[2],
                "password": parts[3]
            }
        
        # Fallback
        return {"server": proxy_str}

    def get_next_proxy(self):
        if not self.proxies:
            return None
        
        proxy = self.proxies[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.proxies)
        return proxy

    def remove_proxy(self, proxy):
        if proxy in self.proxies:
            self.proxies.remove(proxy)
            # Adjust index if necessary? If we remove before current_index, decrement.
            # But we cycle modulo anyway, so maybe just let it be. simpler.
            if self.current_index >= len(self.proxies):
                self.current_index = 0

    def has_proxies(self):
        return len(self.proxies) > 0
