import base64
import logging
import struct
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN = "8673271472:AAEr6mnjCIpJvENgO5NKbYFYykqSEbh7U8k"
CHAT_ID = "7204352317"

CHECK_INTERVAL = 10 * 60  # 10 minutes
COOLDOWN = 60 * 60  # 1 hour suppress after alert

STEAM_API = "https://api.steampowered.com/IPhysicalGoodsService/CheckInventoryAvailableByPackage/v1"
STORE_URL = "https://store.steampowered.com/sale/steamdeckrefurbished/?cc=NL"
COUNTRY = "NL"

MODELS: dict[int, str] = {
    1202542: "Steam Deck 512 GB OLED  — 459€",
    1202547: "Steam Deck 1TB OLED  — 549€",
    903905: "Steam Deck 64 GB LCD  — 299€",
    903906: "Steam Deck 256 GB LCD  — 339€",
    903907: "Steam Deck 512 GB LCD  — 379€",
}


# --- protobuf helpers (tiny subset, no library needed) ---

def _encode_varint(value: int) -> bytes:
    buf = bytearray()
    while value > 0x7F:
        buf.append((value & 0x7F) | 0x80)
        value >>= 7
    buf.append(value & 0x7F)
    return bytes(buf)


def _decode_varint(data: bytes, offset: int = 0) -> tuple[int, int]:
    result = 0
    shift = 0
    while offset < len(data):
        b = data[offset]
        result |= (b & 0x7F) << shift
        offset += 1
        if (b & 0x80) == 0:
            break
        shift += 7
    return result, offset


def _build_request(package_id: int, country: str) -> str:
    """Build base64-encoded protobuf for CheckInventoryAvailableByPackage."""
    # field 1 (varint) = package_id
    payload = b"\x08" + _encode_varint(package_id)
    # field 2 (length-delimited string) = country code
    country_bytes = country.encode()
    payload += b"\x12" + _encode_varint(len(country_bytes)) + country_bytes
    return base64.b64encode(payload).decode()


def _parse_response(data: bytes) -> bool:
    """Parse protobuf response; field 1 = inventory available (bool)."""
    if not data:
        return False
    tag, offset = _decode_varint(data, 0)
    field_number = tag >> 3
    if field_number == 1:
        value, _ = _decode_varint(data, offset)
        return value == 1
    return False


# --- core logic ---

def check_stock(session: requests.Session | None = None) -> dict[int, bool]:
    """Check availability for every model. Returns {package_id: available}."""
    s = session or requests.Session()
    results: dict[int, bool] = {}
    for pkg_id in MODELS:
        encoded = _build_request(pkg_id, COUNTRY)
        try:
            resp = s.get(STEAM_API, params={"input_protobuf_encoded": encoded}, timeout=15)
            resp.raise_for_status()
            available = _parse_response(resp.content)
            results[pkg_id] = available
        except Exception:
            log.exception("Failed to check package %s", pkg_id)
            results[pkg_id] = False
    return results


def send_telegram(text: str) -> bool:
    """Send a message via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
        resp.raise_for_status()
        log.info("Telegram message sent")
        return True
    except Exception:
        log.exception("Failed to send Telegram message")
        return False


@dataclass
class StockMonitor:
    cooldowns: dict[int, datetime] = field(default_factory=dict)

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def run_check(self) -> None:
        log.info("Checking stock...")
        results = check_stock()
        now = self._now()

        in_stock = []
        for pkg_id, available in results.items():
            name = MODELS[pkg_id]
            if available:
                cooldown_until = self.cooldowns.get(pkg_id)
                if cooldown_until and now < cooldown_until:
                    log.info("  %s — IN STOCK (alert suppressed until %s)", name, cooldown_until)
                    continue
                log.info("  %s — IN STOCK!", name)
                in_stock.append(name)
                self.cooldowns[pkg_id] = now + timedelta(seconds=COOLDOWN)
            else:
                log.info("  %s — out of stock", name)

        if in_stock:
            items = "\n".join(f"✅ {name}" for name in in_stock)
            msg = (
                f"<b>🎮 Steam Deck Refurbished — Stock Alert!</b>\n\n"
                f"{items}\n\n"
                f"<a href=\"{STORE_URL}\">Buy now →</a>"
            )
            send_telegram(msg)

    def loop(self) -> None:
        log.info("Steam Deck stock monitor started (every %ds)", CHECK_INTERVAL)
        while True:
            try:
                self.run_check()
            except Exception:
                log.exception("Unexpected error in check loop")
            log.info("Next check in %d minutes", CHECK_INTERVAL // 60)
            time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    StockMonitor().loop()
