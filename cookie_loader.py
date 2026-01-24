def parse_netscape_cookies(file_path):
    cookies = []
    with open(file_path, 'r') as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            
            parts = line.split('\t')
            if len(parts) >= 7:
                # Netscape format: domain, flag, path, secure, expiration, name, value
                domain = parts[0]
                # flag = parts[1] # TRUE/FALSE - treated as hostOnly/etc?
                path = parts[2]
                secure = parts[3].upper() == 'TRUE'
                # expiration = parts[4]
                name = parts[5]
                value = parts[6].strip()
                
                cookie = {
                    'name': name,
                    'value': value,
                    'domain': domain,
                    'path': path,
                    'secure': secure
                }
                cookies.append(cookie)
    return cookies

def update_cookie_in_file(file_path, cookie_name, cookie_value, domain=".cardmarket.com"):
    """
    Updates or adds a cookie in the Netscape cookie file.
    If the cookie exists (matching name), its value is updated.
    If not, it is appended.
    """
    lines = []
    found = False
    
    # Read existing lines
    try:
        with open(file_path, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        # If file doesn't exist, we'll start with a header
        lines = ["# Netscape HTTP Cookie File\n\n"]

    new_lines = []
    # Netscape format: domain, flag, path, secure, expiration, name, value
    # We'll use a standard template for the new/updated cookie
    # Expiration: ~1 year from now (approx 3e7 seconds) -> just use a large timestamp or keep existing
    import time
    timestamp = int(time.time()) + 31536000
    
    # domain	TRUE	/	TRUE	expiration	name	value
    new_line = f"{domain}\tTRUE\t/\tTRUE\t{timestamp}\t{cookie_name}\t{cookie_value}\n"

    for line in lines:
        if line.strip().startswith("#") or not line.strip():
            new_lines.append(line)
            continue
        
        parts = line.split('\t')
        if len(parts) >= 7:
            name = parts[5]
            if name == cookie_name:
                new_lines.append(new_line)
                found = True
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(new_line)

    with open(file_path, 'w') as f:
        f.writelines(new_lines)
