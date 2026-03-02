import requests
import time
from bs4 import BeautifulSoup
from telegram import Bot

# ===== AYARLAR =====
URL = "https://store.steampowered.com/sale/steamdeckrefurbished/?cc=NL"
CHECK_INTERVAL = 600  # 10 dakika
SOLD_OUT_THRESHOLD = 5  # Şu an 5 model var

# TOKEN VE CHAT_ID (BURAYA KENDİ TOKENINI YAZ)
TELEGRAM_TOKEN = "8673271472:AAEr6mnjCIpJvENgO5NKbYFYykqSEbh7U8k"
CHAT_ID = "7204352317"

bot = Bot(token=TELEGRAM_TOKEN)

print("Bot başlatıldı...")

def check_stock():
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.9"
    }

    response = requests.get(URL, headers=headers, timeout=15)
    soup = BeautifulSoup(response.text, "html.parser")

    text = soup.get_text().lower()

    keywords = [
        "tükendi",
        "out of stock",
        "uitverkocht"
    ]

    sold_out_count = sum(text.count(word) for word in keywords)

    print("Toplam stokta yok sayısı:", sold_out_count)

    return sold_out_count < SOLD_OUT_THRESHOLD


while True:
    try:
        if check_stock():
            print("Stok bulundu! Bildirim gönderiliyor...")
            bot.send_message(
                chat_id=CHAT_ID,
                text="🚨 Steam Deck Refurb stokta olabilir!\n" + URL
            )
            time.sleep(3600)  # 1 saat bekle (spam önleme)
        else:
            print("Stok yok.")
    except Exception as e:
        print("Hata:", e)

    time.sleep(CHECK_INTERVAL)
