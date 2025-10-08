# app.py
import hmac
import base64
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from flask import Flask, jsonify
from flask_cors import CORS

# -----------------------------------------------------------------------------
# Flask setup
# -----------------------------------------------------------------------------
app = Flask(__name__)
CORS(app)

# -----------------------------------------------------------------------------
# 🔐 YOUR BÓKUN API CREDENTIALS
# -----------------------------------------------------------------------------
ACCESS_KEY = "75dd7122985a493ebcb1c04841ca2d17"
SECRET_KEY = "8495ebd2d7414b8ebfd9d7253b5bdf09"

# -----------------------------------------------------------------------------
# Product configurations
# -----------------------------------------------------------------------------
PRODUCTS = [
    {
        "id": "1084194",
        "name": "Skerries & Dunluce",
        "booking_url": "https://aquaholics.co.uk/pages/boku-test",
    },
    {
        "id": "1087988",
        "name": "Giant's Causeway, Skerries & Dunluce",
        "booking_url": "https://aquaholics.co.uk/pages/giants-causeway-bkuk",
    },
]

LOCAL_TZ = ZoneInfo("Europe/London")

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def generate_signature(secret_key: str, access_key: str, date_str: str, method: str, path: str, query: str = "") -> str:
    """Create Bókun signature per API requirements."""
    message = f"{date_str}{access_key}{method}{path}{query}"
    digest = hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def normalize_date_param(s: str) -> str:
    """Normalize date inputs (strip Z, keep YYYY-MM-DD)."""
    try:
        s_clean = (s or "").replace("Z", "+00:00")
        return datetime.fromisoformat(s_clean).date().strftime("%Y-%m-%d")
    except Exception:
        return (s or "")[:10]


def slot_start_iso_local(slot: dict) -> str | None:
    """Build 'YYYY-MM-DDTHH:MM:SS' in UK time from slot date (ms) + startTime ('HH:MM')."""
    try:
        ms = slot.get("date")
        st = slot.get("startTime")
        if ms is None or not st:
            return None
        dt_local_midnight = datetime.fromtimestamp(ms / 1000, tz=LOCAL_TZ)
        hour, minute = map(int, st.split(":"))
        dt_local = dt_local_midnight.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return dt_local.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None


def fetch_bokun_availability(product_id: str, start_date: str, end_date: str) -> list[dict]:
    """Call the Bókun API for a product's availability."""
    method = "GET"
    path = f"/activity.json/{product_id}/availabilities"
    query = f"?start={start_date}&end={end_date}&lang=EN&currency=ISK&includeSoldOut=false"

    date_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    signature = generate_signature(SECRET_KEY, ACCESS_KEY, date_str, method, path, query)

    headers = {
        "X-Bokun-Date": date_str,
        "X-Bokun-AccessKey": ACCESS_KEY,
        "X-Bokun-Signature": signature,
        "Accept": "application/json",
    }

    url = "https://api.bokun.io" + path + query
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.json()


def to_calendar_events(product: dict, slots: list[dict]) -> list[dict]:
    """Convert Bókun slots → FullCalendar-compatible events."""
    events: list[dict] = []
    for slot in slots:
        start_iso = slot_start_iso_local(slot)
        if not start_iso:
            continue

        spots = slot.get("availabilityCount", 0)
        is_sold_out = slot.get("soldOut", False) or slot.get("unavailable", False)
        base_title = slot.get("activityTitle") or product.get("name") or "Trip"

        # Keep the full title + spots
        title = f"{base_title} - {spots} spots" if isinstance(spots, int) else base_title

        events.append({
            "id": slot.get("id") or f"{product.get('id')}_{start_iso}",
            "title": title,
            "start": start_iso,        # includes time
            "allDay": False,           # ensures time is visible
            "url": None if is_sold_out else product.get("booking_url"),
            "color": "#ef4444" if is_sold_out else "#16a34a",
            "isSoldOut": bool(is_sold_out),
            "timeLabel": slot.get("startTime"),
        })
    return events

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.route("/")
def root():
    return jsonify({"ok": True, "service": "bokun-calendar-backend"})

@app.route("/availability/<start>/<end>")
def availability(start: str, end: str):
    """Merge all products' availabilities into one JSON list."""
    start_date = normalize_date_param(start)
    end_date   = normalize_date_param(end)
    merged: list[dict] = []

    for product in PRODUCTS:
        try:
            slots = fetch_bokun_availability(product["id"], start_date, end_date)
            merged.extend(to_calendar_events(product, slots))
        except Exception as e:
            print(f"[ERROR] Product {product['id']} failed:", e)
            continue

    merged.sort(key=lambda e: e.get("start") or "")
    return jsonify(merged)

# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
