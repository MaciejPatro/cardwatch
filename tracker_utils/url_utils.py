from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

def clean_url(url):
    """
    Removes Cloudflare-related query parameters (starting with __cf) from the URL.
    Returns the cleaned URL.
    """
    if not url:
        return url
        
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query, keep_blank_values=True)
    
    # Filter out keys starting with __cf
    cleaned_params = {k: v for k, v in query_params.items() if not k.startswith('__cf')}
    
    # Reconstruct query string
    new_query = urlencode(cleaned_params, doseq=True)
    
    # Reconstruct URL
    cleaned_url = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment
    ))
    
    return cleaned_url
