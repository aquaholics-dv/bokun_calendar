import requests
from datetime import datetime, timezone
from flask import Flask, jsonify
from flask_cors import CORS
import hmac, hashlib, base64
import os
import traceback

app = Flask(__name__)
CORS(app)  # allow cross-origin requests (Shopify, browsers)

# === CONFIG ===
ACCESS_KEY = "75dd7122985a493ebcb1c04841ca2d17"
SECRET_KEY = "00c39fd375af4b8e8888b483d14335f5"

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
]

# === HELPERS ===
def generate_signature(secret_key, access_key, date_str, method, path, query=""):
    message = f"{date_str}{access_key}{method}{path}{query}"
    digest = hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")

def millis_to_iso(ms):
    """Convert milliseconds since epoch to ISO 8601 string"""
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.isoformat()

def get_availability_for_products(start_date, end_date):
    events = []

    for product in PRODUCTS:
        product_id = product["id"]
        booking_url = product["booking_url"]

        method = "GET"
        path = f"/activity.json/{product_id}/availabilities"
        query = f"?start={start_date}&end={end_date}&lang=EN&currency=ISK&includeSoldOut=false"
        full_path = path + query

        date_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        signature = generate_signature(SECRET_KEY, ACCESS_KEY, date_str, method, path, query)

        headers = {
            "X-Bokun-Date": date_str,
            "X-Bokun-AccessKey": ACCESS_KEY,
            "X-Bokun-Signature": signature,
            "Accept": "application/json",
        }

        url = "https://api.bokun.io" + full_path
        try:
            response = requests.get(url, headers=headers, timeout=10)
            print(f"[DEBUG] GET {url}")
            print(f"[DEBUG] STATUS: {response.status_code}")
            print(f"[DEBUG] BODY: {response.text[:500]}")  # first 500 chars
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print("[ERROR] Bókun API call failed:")
            traceback.print_exc()
            continue  # skip this product

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

    return events

# === ROUTES ===
@app.route("/availability/<start>/<end>")
def availability(start, end):
    try:
        events = get_availability_for_products(start, end)
        return jsonify(events)
    except Exception as e:
        print("[ERROR] Unexpected error in /availability route:")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# === MAIN ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Railway sets PORT automatically
    print(f"[INFO] Starting Flask on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=True)

