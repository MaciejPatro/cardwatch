from bs4 import BeautifulSoup

html = """
<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><!-- Google Tag Manager --><script>window.dataLayer = window.dataLayer || [];function gtag(){dataLayer.push(arguments);}gtag('js', new Date());gtag('config', 'GTM-5T4HNQZ');gtag('consent', 'update', {'ad_personalization':'denied','ad_storage':'denied','ad_user_data':'denied','analytics_storage':'denied'});window.dataLayer.push({'game':'Riftbound','language':'english','userType':'RegSeller','statistics':0,'marketing':0});</script><script>(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src='https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);})(window,document,'script','dataLayer','GTM-5T4HNQZ');</script><!-- End Google Tag Manager --><title>Riftbound Origins Booster Box | Cardmarket</title>
<div class="page-title-container d-flex flex-wrap align-items-baseline text-break"><div class="flex-fill"><h1>Origins Booster Box<span class="h4 text-muted fst-italic fw-normal ">Booster Boxes</span></h1></div>
<div class="image is-riftbound "><img src="https://product-images.s3.cardmarket.com/1657/845721/845721.jpg" alt="Origins Booster Box" class="is-front"></div>
"""

def test():
    soup = BeautifulSoup(html, 'html.parser')
    
    # Test H1
    h1 = soup.find('h1')
    if h1:
        # Cleanup spans as per original script
        for span in h1.find_all('span'):
            span.decompose()
        print(f"Name Found: {h1.get_text(strip=True)}")
    else:
        print("Name NOT Found")
        
    # Test Image
    img_tag = soup.select_one('div.tab-content img')
    if not img_tag:
        img_tag = soup.select_one('div.image img')
        
    if img_tag:
        print(f"Image Found: {img_tag.get('src')}")
    else:
        print("Image NOT Found")

if __name__ == "__main__":
    test()
