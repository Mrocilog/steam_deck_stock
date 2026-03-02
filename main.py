import requests
import time
from telegram import Bot

# ===== AYARLAR =====
CHECK_INTERVAL = 600
TELEGRAM_TOKEN = "8673271472:AAEr6mnjCIpJvENgO5NKbYFYykqSEbh7U8k"
CHAT_ID = "7204352317"

# Refurb modellerin AppID’leri (örnek – gerekirse güncelleriz)
APP_IDS = [
    1675200,  # Steam Deck 64GB
    1675180,  # 256GB
    1675190   # 512GB
]

bot = Bot(token=TELEGRAM_TOKEN)

print("API tabanlı bot başlatıldı...")

def check_stock():
    for appid in APP_IDS:
        url = f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=NL"
        response = requests.get(url, timeout=15)
        data = response.json()

        if not data[str(appid)]["success"]:
            continue

        app_data = data[str(appid)]["data"]

        # Eğer is_free değil ve price_overview varsa satın alınabilir demektir
        if "price_overview" in app_data:
            print(f"AppID {appid} satın alınabilir görünüyor!")
            return True

    print("Hiçbir model satın alınabilir değil.")
    return False


while True:
    try:
        if check_stock():
            bot.send_message(
                chat_id=CHAT_ID,
                text="🚨 Steam Deck Refurb stokta olabilir!"
            )
            time.sleep(3600)
        else:
            print("Stok yok.")
    except Exception as e:
        print("Hata:", e)

    time.sleep(CHECK_INTERVAL)
