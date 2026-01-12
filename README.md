mBot - Google Maps Lead Scraper 🚀

A powerful Python-based automation tool designed to discover business leads on Google Maps. The bot searches for businesses based on specific keywords and locations, extracts contact information, and saves everything directly to a Google Sheet in real-time.

✨ Key Features

Deep Email Extraction: Automatically visits company websites to find contact email addresses that aren't listed directly on Google Maps.

Google Sheets Integration: Seamlessly syncs found leads to a specified Google Spreadsheet.

Smart Usage Tracking: Includes a built-in safety system (usage_stats.json) to monitor API calls and stay within the Google Cloud free tier limits.

Batch Processing: Efficiently handles hundreds of search combinations using a simple targets.csv input file.

Lead Deduplication: Automatically checks the spreadsheet to ensure no duplicate leads are added.

🛠️ Installation

Clone the repository:

git clone [https://github.com/kwahu666/mBot-Google-Maps.git](https://github.com/kwahu666/mBot-Google-Maps.git)
cd mBot-Google-Maps


Install dependencies:

pip install -r requirements.txt


⚙️ Configuration

To protect your sensitive data, the actual configuration files are ignored by Git. Follow these steps to set up the bot:

API Config: Rename config.example.json to config.json and paste your Google Maps API Key.

Google Credentials: Place your Google Cloud Service Account JSON file in the root folder and name it credentials.json.

Spreadsheet Access: Share your target Google Sheet with the client_email address found inside your credentials.json.

Targets: Edit targets.csv to define the keywords and cities you want to scrape (e.g., dentist, New York).

🚀 Usage

Run the bot using the following command:

python main.py


⚠️ Safety & Disclaimer

This tool is for educational purposes. Users are responsible for ensuring their scraping activities comply with the Google Maps Platform Terms of Service and local data privacy laws (like GDPR). The built-in limit is set to 4,950 requests per month to help avoid unexpected charges.

📄 License

This project is open-source and available under the MIT License.