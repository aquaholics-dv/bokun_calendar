@@ -1,116 +1,188 @@
# app.py
import os
import hmac
import base64
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from flask import Flask, jsonify
from flask_cors import CORS
import requests, hmac, hashlib, base64, os
from datetime import datetime, timezone

# --- Flask setup ---
# -----------------------------------------------------------------------------
# App & config
# -----------------------------------------------------------------------------
app = Flask(__name__)
CORS(app)  # Allow CORS so Shopify can fetch data
CORS(app)  # allow Shopify to call this API

# --- Bókun API keys (replace if needed) ---
ACCESS_KEY = "75dd7122985a493ebcb1c04841ca2d17"
SECRET_KEY = "8495ebd2d7414b8ebfd9d7253b5bdf09"
# Read your Bókun API keys from environment variables (recommended)
ACCESS_KEY = os.getenv("BOKUN_ACCESS_KEY", "")
SECRET_KEY = os.getenv("BOKUN_SECRET_KEY", "")

# --- Products you want to display ---
# IMPORTANT: set these in Railway → Variables:
#  BOKUN_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxx
#  BOKUN_SECRET_KEY=xxxxxxxxxxxxxxxxxxxx

# Products you want to show on the calendar
PRODUCTS = [
    {
        "id": "1084194",
        "name": "Skerries & Dunluce",
        "booking_url": "https://aquaholics.co.uk/pages/boku-test"
    },
    {
        "id": "1087988",
        "name": "Giant's Causeway, Skerries & Dunluce",
        "booking_url": "https://aquaholics.co.uk/pages/giants-causeway-bkuk"
    },
    # id = activity/product id in Bókun
    {"id": "1084194", "name": "Skerries & Dunluce", "booking_url": "https://aquaholics.co.uk/pages/boku-test"},
    {"id": "1087988", "name": "Giant's Causeway, Skerries & Dunluce", "booking_url": "https://aquaholics.co.uk/pages/giants-causeway-bkuk"},
]

# --- Bokun Signature Helpers ---

def bokun_date_str():
    """Return UTC date string exactly as Bokun expects."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def generate_signature(secret_key, access_key, date_str, method, path, query=""):
    """Generate signature identical to Bokun Postman pre-request script."""
    message = f"{date_str}{access_key}{method}{path}{query}".strip()
# Show times in UK time
LOCAL_TZ = ZoneInfo("Europe/London")

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def generate_signature(secret_key: str, access_key: str, date_str: str, method: str, path: str, query: str = "") -> str:
    """
    Per Bókun docs: signature = Base64( HMAC-SHA1( secret, date + accessKey + method + path + query ) )
    """
    message = f"{date_str}{access_key}{method}{path}{query}"
    digest = hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha1).digest()
    signature = base64.b64encode(digest).decode("utf-8")
    return base64.b64encode(digest).decode("utf-8")

    # Debug logs for verification
    print("[BOKUN DEBUG] Date:", date_str)
    print("[BOKUN DEBUG] Message:", message)
    print("[BOKUN DEBUG] Signature:", signature)

    return signature
def normalize_date_param(s: str) -> str:
    """
    Accepts 'YYYY-MM-DD' or ISO strings like 'YYYY-MM-DDTHH:MM:SSZ' and returns 'YYYY-MM-DD'.
    """
    try:
        s_clean = (s or "").replace("Z", "+00:00")
        return datetime.fromisoformat(s_clean).date().strftime("%Y-%m-%d")
    except Exception:
        return (s or "")[:10]


def slot_start_iso_local(slot: dict) -> str | None:
    """
    Build a local ISO datetime like '2025-09-22T10:00:00' from:
      - slot['date']       (ms since epoch, local date baseline)
      - slot['startTime']  ('HH:MM')
    No trailing 'Z' so FullCalendar treats it as local time (no timezone shift).
    """
    try:
        ms = slot.get("date")
        st = slot.get("startTime")  # 'HH:MM'
        if ms is None or not st:
            return None

        # Convert ms epoch to LOCAL date so DST is handled
        dt_local_midnight = datetime.fromtimestamp(ms / 1000, tz=LOCAL_TZ)
        hour, minute = map(int, st.split(":"))
        dt_local = dt_local_midnight.replace(hour=hour, minute=minute, second=0, microsecond=0)
        # Return without timezone suffix
        return dt_local.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None


def fetch_bokun_availability(product_id: str, start_date: str, end_date: str) -> list[dict]:
    """
    Calls Bókun availability endpoint for a single product and returns the JSON list.
    """
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
    """
    Transform Bókun slots to FullCalendar events.
    """
    events: list[dict] = []
    for slot in slots:
        start_iso = slot_start_iso_local(slot)
        if not start_iso:
            continue

        spots = slot.get("availabilityCount", 0)
        is_sold_out = slot.get("soldOut", False) or slot.get("unavailable", False)

        # Prefer Bókun's full activityTitle; fall back to configured product name
        base_title = slot.get("activityTitle") or product.get("name") or "Trip"
        full_title = f"{base_title} - {spots} spots" if isinstance(spots, int) else base_title

        events.append({
            "id": slot.get("id") or f"{product.get('id')}_{start_iso}",
            "title": full_title,                # full title with spots
            "start": start_iso,                 # includes time, local
            "allDay": False,                    # ensure time is displayed
            "url": None if is_sold_out else product.get("booking_url"),
            # cosmetic fields (optional)
            "color": "#ef4444" if is_sold_out else "#16a34a",
            "isSoldOut": bool(is_sold_out),
            "timeLabel": slot.get("startTime"), # convenient for custom rendering
        })
    return events

def millis_to_iso(ms):
    """Convert milliseconds since epoch to ISO 8601 string."""
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.isoformat()

# --- Bokun API Request ---
# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.route("/")
def root():
    return jsonify({
        "ok": True,
        "service": "bokun-calendar-backend",
        "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    })

def get_availability_for_products(start_date, end_date):
    events = []

@app.route("/availability/<start>/<end>")
def availability(start: str, end: str):
    """
    Returns a merged list of events for all PRODUCTS within start..end (inclusive).
    Accepts date-only or ISO; we normalise to 'YYYY-MM-DD' for Bókun.
    """
    # Guard: ensure keys exist
    if not ACCESS_KEY or not SECRET_KEY:
        return jsonify({"error": "Missing BOKUN_ACCESS_KEY / BOKUN_SECRET_KEY env vars"}), 500

    start_date = normalize_date_param(start)
    end_date   = normalize_date_param(end)

    merged: list[dict] = []
    for product in PRODUCTS:
        product_id = product["id"]
        booking_url = product["booking_url"]

        method = "GET"
        path = f"/activity.json/{product_id}/availabilities"
        query = f"?start={start_date}&end={end_date}&lang=EN&currency=ISK&includeSoldOut=false"
        full_path = path + query

        date_str = bokun_date_str()
        signature = generate_signature(SECRET_KEY, ACCESS_KEY, date_str, method, path, query)

        headers = {
            "X-Bokun-Date": date_str,
            "X-Bokun-AccessKey": ACCESS_KEY,
            "X-Bokun-Signature": signature,
            "Accept": "application/json",
        }

        url = "https://api.bokun.io" + full_path
        print("[BOKUN DEBUG] Request URL:", url)

        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            for slot in data:
                spots = slot.get("availabilityCount", 0)
                is_sold_out = slot.get("soldOut", False) or slot.get("unavailable", False)
                start_time = millis_to_iso(slot["date"]) if "date" in slot else None

                events.append({
                    "title": f"{product['name']} - {spots} spots",
                    "start": start_time,
                    "color": "green" if not is_sold_out else "red",
                    "url": booking_url if not is_sold_out else None,
                })

        except requests.RequestException as e:
            print("[ERROR] Request failed for", product_id, ":", e)

    return events

# --- Flask route for frontend ---

@app.route("/availability/<start>/<end>")
def availability(start, end):
    try:
        events = get_availability_for_products(start, end)
        return jsonify(events)
    except Exception as e:
        print("[ERROR]", e)
        return jsonify({"error": str(e)}), 500

# --- Run Flask locally or on Railway ---
            slots = fetch_bokun_availability(product["id"], start_date, end_date)
            merged.extend(to_calendar_events(product, slots))
        except requests.HTTPError as http_err:
            # Log and continue so one failing product doesn't break the response
            print(f"[ERROR] HTTP for product {product['id']}: {http_err}")
            continue
        except Exception as e:
            print(f"[ERROR] product {product['id']}: {e}")
            continue

    # Sort by start datetime (string sort works with YYYY-MM-DDTHH:MM:SS)
    merged.sort(key=lambda e: e.get("start") or "")
    return jsonify(merged)


# -----------------------------------------------------------------------------
# Entry
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Railway sets PORT automatically
    print(f"[INFO] Starting Flask on port {port}...")
    # Railway provides PORT; default to 5000 locally
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
