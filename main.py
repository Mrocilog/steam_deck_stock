import requests
import time
import logging
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.error import TelegramError

# ===== AYARLAR =====
CHECK_INTERVAL = 600       # Her 10 dakikada bir kontrol
COOLDOWN_AFTER_ALERT = 3600  # Bildirim sonrası 1 saat bekle

TELEGRAM_TOKEN = "8673271472:AAEr6mnjCIpJvENgO5NKbYFYykqSEbh7U8k"
CHAT_ID = "7204352317"

SALE_URL = "https://store.steampowered.com/sale/steamdeckrefurbished/?cc=NL"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

COOKIES = {
    "birthtime": "786240001",
    "mature_content": "1",
    "Store_EnableAdultContent": "1",
    "cc": "NL",
    "lastagecheckage": "1-0-1995",
}

# ===== LOGGING =====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ===== BOT =====
bot = Bot(token=TELEGRAM_TOKEN)


def check_stock() -> bool:
    """
    Scrapes the Steam Deck Refurbished sale page and returns True
    if at least one model appears to be purchasable.
    """
    try:
        response = requests.get(
            SALE_URL,
            headers=HEADERS,
            cookies=COOKIES,
            timeout=20,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        log.error("HTTP isteği başarısız: %s", e)
        return False

    soup = BeautifulSoup(response.text, "html.parser")
    page_text = soup.get_text(separator=" ").lower()

    # --- Stokta yok sinyalleri ---
    out_of_stock_phrases = [
        "out of stock",
        "sold out",
        "currently unavailable",
        "not available",
    ]
    for phrase in out_of_stock_phrases:
        if phrase in page_text:
            log.info("'%s' ifadesi bulundu → stok yok.", phrase)
            return False

    # --- Satın alınabilir sinyalleri ---
    # 1) Gerçek "Sepete Ekle" butonları
    add_to_cart_buttons = soup.select("a.btn_addtocart, button.btn_addtocart")

    # 2) Fiyat gösterilen kutular (fiyat varsa ürün listeleniyordur)
    price_elements = soup.select(".discount_final_price, .price")

    # 3) Sayfa gerçekten yüklendi mi? (Steam bazen boş/hata sayfası döner)
    deck_mentioned = "steam deck" in page_text

    log.info(
        "Sonuçlar → Sepet butonu: %d | Fiyat elementi: %d | 'Steam Deck' sayfada: %s",
        len(add_to_cart_buttons),
        len(price_elements),
        deck_mentioned,
    )

    if not deck_mentioned:
        log.warning("Sayfa Steam Deck içermiyor – Steam yanlış sayfa döndürmüş olabilir.")
        return False

    # Hem buton hem fiyat varsa güvenli pozitif
    if add_to_cart_buttons and price_elements:
        log.info("✅ Stok tespit edildi!")
        return True

    # Sadece fiyat elementi varsa (buton CSS ile gizlenmiş olabilir)
    if price_elements:
        log.info("⚠️  Fiyat elementi var ama sepet butonu yok – muhtemelen stokta yok.")
        return False

    return False


def send_notification():
    message = (
        "🚨 *Steam Deck Refurb Stokta!*\n\n"
        "Hemen kontrol et:\n"
        f"{SALE_URL}"
    )
    try:
        bot.send_message(
            chat_id=CHAT_ID,
            text=message,
            parse_mode="Markdown",
        )
        log.info("Telegram bildirimi gönderildi.")
    except TelegramError as e:
        log.error("Telegram bildirimi gönderilemedi: %s", e)


def main():
    log.info("Steam Deck Refurb stok botu başlatıldı. Kontrol aralığı: %ds", CHECK_INTERVAL)

    while True:
        try:
            in_stock = check_stock()

            if in_stock:
                send_notification()
                log.info("Bildirim gönderildi. %d saniye bekleniyor...", COOLDOWN_AFTER_ALERT)
                time.sleep(COOLDOWN_AFTER_ALERT)
            else:
                log.info("Stok yok. %d saniye sonra tekrar kontrol edilecek.", CHECK_INTERVAL)
                time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            log.info("Bot durduruldu.")
            break
        except Exception as e:
            log.exception("Beklenmeyen hata: %s", e)
            time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
