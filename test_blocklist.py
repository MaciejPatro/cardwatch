
from blocklist_manager import load_blocklist, is_blocked

def test_blocklist_logic():
    print("Testing Blocklist Logic...")
    
    # 1. Load (should find the file)
    load_blocklist()
    
    # 2. Test Blocked IDs
    blocked_ids = [692261, 692264, 692265, 696389, 696390]
    for bid in blocked_ids:
        assert is_blocked(product_id=bid), f"ID {bid} should be blocked!"
        print(f"PASS: ID {bid} blocked.")
        
    # 3. Test Blocked URLs
    blocked_urls = [
        "https://www.cardmarket.com/en/OnePiece/Products/Preconstructed-Decks/Super-PreRelease-Starter-Deck-Straw-Hat-Crew",
        "https://www.cardmarket.com/en/OnePiece/Products/Preconstructed-Decks/Starter-Deck-ST01-ST04-Deck-Set"
    ]
    for url in blocked_urls:
        assert is_blocked(url=url), f"URL {url} should be blocked!"
        print(f"PASS: URL {url} blocked.")
        
    # 4. Test Allowed
    assert not is_blocked(product_id=12345), "ID 12345 should NOT be blocked!"
    print("PASS: ID 12345 allowed.")
    
    assert not is_blocked(url="https://example.com"), "URL https://example.com should NOT be blocked!"
    print("PASS: URL https://example.com allowed.")
    
    print("\nAll blocklist tests passed!")

if __name__ == "__main__":
    test_blocklist_logic()
