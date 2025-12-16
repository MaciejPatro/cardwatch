import json
import os
import logging

logger = logging.getLogger(__name__)

BLOCKLIST_FILE = "blocklist.json"

_blocked_ids = None
_blocked_urls = None

def load_blocklist():
    """Loads the blocklist from the JSON file into memory."""
    global _blocked_ids, _blocked_urls
    
    if not os.path.exists(BLOCKLIST_FILE):
        _blocked_ids = set()
        _blocked_urls = set()
        return

    try:
        with open(BLOCKLIST_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            _blocked_ids = set(data.get("product_ids", []))
            _blocked_urls = set(data.get("urls", []))
            logger.info(f"Loaded blocklist: {len(_blocked_ids)} IDs, {len(_blocked_urls)} URLs.")
    except Exception as e:
        logger.error(f"Failed to load blocklist: {e}")
        # Fallback to empty to allow operation
        _blocked_ids = set()
        _blocked_urls = set()

def is_blocked(product_id=None, url=None):
    """
    Checks if the given product_id or url is in the blocklist.
    Returns True if blocked, False otherwise.
    """
    global _blocked_ids, _blocked_urls

    # Lazy load
    if _blocked_ids is None:
        load_blocklist()
    
    if product_id is not None and product_id in _blocked_ids:
        return True
    
    if url is not None and url in _blocked_urls:
        return True
    
    return False
