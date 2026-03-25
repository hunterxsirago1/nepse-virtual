import requests
from bs4 import BeautifulSoup
import datetime

def test_ajax():
    url = "https://www.sharesansar.com/ajaxtodayshareprice"
    session = requests.Session()
    
    # Get the main page first to get cookies and potentially a token
    main_url = "https://www.sharesansar.com/today-share-price"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    }
    print("Fetching main page for cookies...")
    r = session.get(main_url, headers=headers)
    
    # Try to find a CSRF token in the HTML
    soup = BeautifulSoup(r.text, 'html.parser')
    token = None
    # Meta tag or hidden input
    token_meta = soup.find('meta', {'name': 'csrf-token'})
    if token_meta:
        token = token_meta.get('content')
    
    if not token:
        # Check for any hidden input named _token
        token_input = soup.find('input', {'name': '_token'})
        if token_input:
            token = token_input.get('value')
            
    print(f"Token found: {token}")
    
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    payload = {
        '_token': token,
        'sector': 'all_sec',
        'date': today
    }
    
    ajax_headers = headers.copy()
    ajax_headers.update({
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Referer': main_url
    })
    
    print(f"Fetching AJAX data for {today}...")
    r_ajax = session.post(url, data=payload, headers=ajax_headers)
    print(f"AJAX Status: {r_ajax.status_code}")
    
    if r_ajax.status_code == 200:
        print("AJAX Response starts with:")
        print(r_ajax.text[:500])
        if "Symbol" in r_ajax.text or "SYMBOL" in r_ajax.text:
            print("SUCCESS: Found Symbol in AJAX response!")
        else:
            print("FAILURE: AJAX response does not contain data.")
    else:
        print(f"AJAX failed: {r_ajax.text[:200]}")

if __name__ == "__main__":
    test_ajax()
