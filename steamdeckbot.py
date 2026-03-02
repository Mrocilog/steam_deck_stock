import os
import requests
import time
from bs4 import BeautifulSoup
from telegram import Bot

URL = "https://store.steampowered.com/sale/steamdeckrefurbished/?cc=NL"
CHECK_INTERVAL = 600  # 10 dakika

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

bot = Bot(token=TELEGRAM_TOKEN)

def check_stock():
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(URL, headers=headers)
    soup = BeautifulSoup(r.text, "html.parser")

    text = soup.get_text()
    sold_out_count = text.count("Tükendi")

    print("Tükendi sayısı:", sold_out_count)

    if sold_out_count < 5:
        return True
    return False

def notify():
    bot.send_message(
        chat_id=CHAT_ID,
        text="🚨 Refurbished Steam Deck stokta olabilir!\n" + URL
    )

while True:
    try:
        if check_stock():
            notify()
            time.sleep(3600)  # spam yapmasın diye 1 saat bekle
        else:
            print("Stok yok.")
    except Exception as e:
        print("Hata:", e)

    time.sleep(CHECK_INTERVAL)
