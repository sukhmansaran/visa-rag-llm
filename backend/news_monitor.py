import requests
from bs4 import BeautifulSoup
import time

class NewsMonitor:
    def __init__(self):
        # Canada-only focus (other sources commented out)
        self.sources = [
            "https://www.canada.ca/en/immigration-refugees-citizenship/news.html",
            # Other countries commented out — Canada-only focus
            # "https://www.schengenvisainfo.com/news/",
        ]

    def fetch_latest_news(self):
        news_items = []
        for url in self.sources:
            try:
                # Mocking the request for now to avoid network issues during dev without internet access confirmation
                # response = requests.get(url) 
                # soup = BeautifulSoup(response.content, 'html.parser')
                # ... parsing logic ...
                
                # Returning dummy data for demonstration — Canada-only focus
                news_items.append({
                    "title": "Canada Updates GIC Amount for International Students",
                    "summary": "Starting 2025, the GIC amount required is CAD 20,635...",
                    "link": url,
                    "date": "2025-01-15"
                })
            except Exception as e:
                print(f"Error fetching news from {url}: {e}")
        
        return news_items

monitor = NewsMonitor()
