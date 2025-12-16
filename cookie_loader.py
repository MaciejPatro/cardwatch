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
