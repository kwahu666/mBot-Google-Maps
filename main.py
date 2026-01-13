import os
import json
import csv
import time
import re
import asyncio
import aiohttp
from datetime import datetime
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Load environment variables
load_dotenv()

# Configuration
def get_config(key, default=None):
    val = os.getenv(key)
    if val: return val
    if os.path.exists('config.json'):
        try:
            with open('config.json', 'r') as f:
                return json.load(f).get(key, default)
        except:
            pass
    return default

MAPS_API_KEY = get_config("MAPS_API_KEY")
GOOGLE_SHEETS_NAME = get_config("GOOGLE_SHEETS_NAME", "Kontakty z map")
SERVICE_ACCOUNT_FILE = get_config("SERVICE_ACCOUNT_FILE", "credentials.json")

# API Constants
PLACES_API_URL = "https://places.googleapis.com/v1/places:searchText"
# Requesting: Display Name, Formatted Address, Website URI, National Phone Number, ID
FIELD_MASK = "places.displayName,places.formattedAddress,places.websiteUri,places.nationalPhoneNumber,places.id"

# --- SYSTEM FUNCTIONS (LIMITS & DB) ---

def check_and_update_limit(increment=1):
    stats_file = 'usage_stats.json'
    now = datetime.now()
    current_month = now.strftime("%Y-%m")
    try:
        with open(stats_file, 'r') as f:
            stats = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        stats = {"month": current_month, "total_requests": 0}

    if stats['month'] != current_month:
        stats = {"month": current_month, "total_requests": 0}

    # Limit set to 5000 requests (searches)
    if stats['total_requests'] >= 5000:
        print("!!! LIMIT 5000 REQUESTS REACHED !!!")
        return False

    stats['total_requests'] += increment
    with open(stats_file, 'w') as f:
        json.dump(stats, f)
    return True

def get_existing_ids(sheet):
    try:
        data = sheet.get_all_values()
        if not data or len(data) <= 1:
            return set()
        # Place ID is at index 6 (7th column)
        return {row[6] for row in data if len(row) > 6}
    except Exception as e:
        print(f"Error reading sheet: {e}")
        return set()

# --- WEB SCRAPING FUNCTIONS ---

def get_emails_from_text(text):
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    return set([e.lower() for e in emails if not e.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg'))])

async def fetch_url(session, url, timeout=10):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}
    try:
        async with session.get(url, timeout=timeout, headers=headers) as response:
            if response.status == 200:
                # Limit size to avoid memory issues with huge pages
                return await response.text()
    except:
        pass
    return None

async def find_email_deep_scan(session, base_url):
    if not base_url:
        return ""

    # 1. Scan Homepage
    text = await fetch_url(session, base_url)
    if not text:
        return "Błąd połączenia"

    found = get_emails_from_text(text)
    if found:
        return ", ".join(found)

    # 2. Scan Contact Pages
    soup = BeautifulSoup(text, 'html.parser')
    keywords = ['kontakt', 'contact', 'o-nas', 'about', 'regulamin', 'polityka']
    links = set()

    for a in soup.find_all('a', href=True):
        href = a['href']
        full_url = urljoin(base_url, href)
        # Check if keyword in href or text
        if any(kw in href.lower() or kw in a.get_text().lower() for kw in keywords):
             if base_url in full_url: # Only internal links usually
                 links.add(full_url)

    # Limit deep scan to first 3 links to save time
    tasks = []
    for link in list(links)[:3]:
        tasks.append(fetch_url(session, link, timeout=7))

    results = await asyncio.gather(*tasks)

    all_emails = set()
    for res_text in results:
        if res_text:
            all_emails.update(get_emails_from_text(res_text))

    if all_emails:
        return ", ".join(all_emails)

    return "Brak maila"

# --- GOOGLE MAPS API ---

async def search_places(session, query, page_token=None):
    if not check_and_update_limit(1):
        return None, None

    payload = {
        "textQuery": query,
        "pageSize": 20
    }
    if page_token:
        payload["pageToken"] = page_token

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": MAPS_API_KEY,
        "X-Goog-FieldMask": FIELD_MASK
    }

    try:
        async with session.post(PLACES_API_URL, json=payload, headers=headers) as response:
            if response.status != 200:
                print(f"API Error: {response.status} - {await response.text()}")
                return [], None

            data = await response.json()
            return data.get('places', []), data.get('nextPageToken')
    except Exception as e:
        print(f"Request Error: {e}")
        return [], None

# --- MAIN LOGIC ---

async def process_target(session, sheet, target, existing_ids):
    query = f"{target['keyword']} {target['city']}"
    print(f"\n--- Szukam: {query} ---")

    next_page_token = None
    page_count = 0

    while page_count < 3: # Max 3 pages (60 results)
        places, next_page_token = await search_places(session, query, next_page_token)

        if places is None: # Error or Limit
            break

        if not places:
            # No results or end of list
            if not next_page_token:
                break
            # If no places but token exists, maybe just metadata? Continue.

        rows_to_add = []
        tasks = []
        place_details_list = []

        for place in places:
            pid = place.get('id')
            if pid in existing_ids:
                continue

            # Prepare data for async processing
            name = place.get('displayName', {}).get('text', '')
            address = place.get('formattedAddress', '')
            phone = place.get('nationalPhoneNumber', '')
            website = place.get('websiteUri', '')

            place_details_list.append({
                'name': name,
                'address': address,
                'phone': phone,
                'website': website,
                'id': pid
            })

            # Create async task for email scraping if website exists
            if website:
                tasks.append(find_email_deep_scan(session, website))
            else:
                tasks.append(asyncio.sleep(0)) # Dummy task

        if not place_details_list:
            if not next_page_token: break
            page_count += 1
            # Wait a bit before next page
            await asyncio.sleep(2)
            continue

        # Run all email scans concurrently
        print(f"Skanowanie maili dla {len(place_details_list)} nowych firm...")
        email_results = await asyncio.gather(*tasks)

        for i, details in enumerate(place_details_list):
            email = email_results[i] if isinstance(email_results[i], str) else ""
            if email == "No email": email = "Brak maila"
            # If result of sleep(0) which is None/void, handle it?
            # sleep(0) returns None.
            if not email and not details['website']:
                email = "Brak WWW"

            print(f"Nowy lead: {details['name']}")

            row = [
                details['name'],
                email,
                details['phone'],
                details['website'],
                details['address'],
                target['keyword'],
                details['id']
            ]
            rows_to_add.append(row)
            existing_ids.add(details['id'])

        # Batch update to Sheets (Sync operation)
        if rows_to_add:
            try:
                sheet.append_rows(rows_to_add)
                print(f"Dodano {len(rows_to_add)} wierszy do Arkusza.")
            except Exception as e:
                print(f"Błąd zapisu do Arkusza: {e}")

        if not next_page_token:
            break

        page_count += 1
        await asyncio.sleep(2)

async def main_async():
    if not MAPS_API_KEY:
        print("Błąd: Brak MAPS_API_KEY. Ustaw zmienną środowiskową lub plik config.json")
        return

    # 1. Setup Google Sheets
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, scope)
        gc = gspread.authorize(creds)
        sheet = gc.open(GOOGLE_SHEETS_NAME).sheet1
        
        # Init header if empty
        if not sheet.get_all_values():
            sheet.append_row(["Nazwa", "E-mail", "Telefon", "WWW", "Adres", "Branża", "Place ID"])
    except Exception as e:
        print(f"Błąd połączenia z Arkuszem: {e}")
        return

    existing_ids = get_existing_ids(sheet)

    # 2. Read Targets
    if not os.path.exists('targets.csv'):
         print("Błąd: Brak pliku targets.csv")
         return

    with open('targets.csv', 'r', encoding='utf-8') as f:
        targets = list(csv.DictReader(f))

    async with aiohttp.ClientSession() as session:
        for target in targets:
            await process_target(session, sheet, target, existing_ids)

    print("\n--- Zakończono! Wszystkie strony przeszukane. ---")

if __name__ == "__main__":
    asyncio.run(main_async())
