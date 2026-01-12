import json
import csv
import time
import re
import requests
import googlemaps
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# --- FUNKCJE SYSTEMOWE (LIMITY I BAZA) ---

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

    if stats['total_requests'] >= 4950:
        print("!!! LIMIT 5000 OSIĄGNIĘTY !!!")
        return False

    stats['total_requests'] += increment
    with open(stats_file, 'w') as f:
        json.dump(stats, f)
    return True

def get_existing_ids(sheet):
    data = sheet.get_all_values()
    if not data or len(data) <= 1:
        return set()
    return {row[6] for row in data if len(row) > 6}

# --- FUNKCJE SKANOWANIA WWW ---

def get_emails_from_text(text):
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    return set([e.lower() for e in emails if not e.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg'))])

def find_email_deep_scan(base_url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}
    try:
        response = requests.get(base_url, timeout=10, headers=headers)
        found = get_emails_from_text(response.text)
        if found: return ", ".join(found)

        soup = BeautifulSoup(response.text, 'html.parser')
        keywords = ['kontakt', 'contact', 'o-nas', 'regulamin', 'polityka']
        links = [urljoin(base_url, a['href']) for a in soup.find_all('a', href=True) 
                 if any(kw in a['href'].lower() or kw in a.get_text().lower() for kw in keywords)]

        for link in list(set(links))[:3]:
            try:
                res = requests.get(link, timeout=7, headers=headers)
                emails = get_emails_from_text(res.text)
                if emails: return ", ".join(emails)
            except: continue
        return "Brak maila"
    except: return "Błąd połączenia"

# --- GŁÓWNA LOGIKA ---

def main():
    try:
        with open('config.json', 'r') as f: config = json.load(f)
    except FileNotFoundError:
        print("Błąd: Brak pliku config.json")
        return

    # 1. Połączenie z Google Sheets
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(config['SERVICE_ACCOUNT_FILE'], scope)
        gc = gspread.authorize(creds)
        sheet = gc.open(config['GOOGLE_SHEETS_NAME']).sheet1
        
        if not sheet.get_all_values():
            sheet.append_row(["Nazwa", "E-mail", "Telefon", "WWW", "Adres", "Branża", "Place ID"])
    except Exception as e:
        print(f"Błąd połączenia z Arkuszem: {e}")
        return

    existing_ids = get_existing_ids(sheet)
    gmaps = googlemaps.Client(key=config['MAPS_API_KEY'])

    # 2. Przetwarzanie celów
    with open('targets.csv', 'r', encoding='utf-8') as f:
        targets = list(csv.DictReader(f))

    for target in targets:
        query = f"{target['keyword']} {target['city']}"
        print(f"\n--- Szukam: {query} ---")
        
        next_page_token = None
        page_count = 0

        while page_count < 3: # Google pozwala na max 3 strony (łącznie 60 wyników)
            if not check_and_update_limit(): break
            
            # Pobieranie listy wyników (paczka 20 sztuk)
            if next_page_token:
                # Trzeba chwilę poczekać, inaczej Google zwróci błąd INVALID_REQUEST przy tokenie
                time.sleep(2)
                places = gmaps.places(query=query, page_token=next_page_token)
            else:
                places = gmaps.places(query=query)
            
            results = places.get('results', [])
            for place in results:
                pid = place['place_id']
                if pid in existing_ids:
                    continue

                if not check_and_update_limit(): break
                
                # Pobieramy szczegóły tylko dla NOWYCH firm
                details = gmaps.place(place_id=pid, 
                                     fields=['name', 'formatted_phone_number', 'website', 'formatted_address'])['result']
                
                www = details.get('website')
                if www:
                    print(f"Nowy lead: {details.get('name')}")
                    email = find_email_deep_scan(www)
                    
                    sheet.append_row([
                        details.get('name'), email, details.get('formatted_phone_number'),
                        www, details.get('formatted_address'), target['keyword'], pid
                    ])
                    existing_ids.add(pid)
                    time.sleep(1) # Przerwa między dopisywaniem do arkusza

            # Sprawdzenie, czy jest kolejna strona
            next_page_token = places.get('next_page_token')
            if not next_page_token:
                break
            
            page_count += 1
            print(f"...pobieram kolejną stronę wyników dla {target['city']}...")

    print("\n--- Zakończono! Wszystkie strony przeszukane. ---")

if __name__ == "__main__":
    main()