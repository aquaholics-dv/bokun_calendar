"""Minimal Flask application exposing Bokun availability as FullCalendar events."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import requests
from flask import Flask, jsonify
from flask_cors import CORS

# --- Flask setup ---
app = Flask(__name__)
CORS(app)  # Allow CORS so Shopify can fetch data

# --- Bókun API keys (replace if needed) ---
ACCESS_KEY = "75dd7122985a493ebcb1c04841ca2d17"
SECRET_KEY = "00c39fd375af4b8e8888b483d14335f5"

@dataclass(frozen=True)
class Product:
    """Small container describing a Bokun product we want to expose."""

    id: str
    name: str
    booking_url: str


# --- Products you want to display ---
PRODUCTS: List[Product] = [
    Product(
        id="1084194",
        name="Skerries & Dunluce",
        booking_url="https://aquaholics.co.uk/pages/boku-test",
    ),
    Product(
        id="1087988",
        name="Giant's Causeway, Skerries & Dunluce",
        booking_url="https://aquaholics.co.uk/pages/giants-causeway-bkuk",
    ),
]

# --- Bokun Signature Helpers ---

def bokun_date_str():
    """Return UTC date string exactly as Bokun expects."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def generate_signature(
    secret_key: str,
    access_key: str,
    date_str: str,
    method: str,
    path: str,
    query: str = "",
) -> str:
    """Generate signature identical to Bokun Postman pre-request script."""

    message = f"{date_str}{access_key}{method}{path}{query}".strip()
    digest = hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha1).digest()
    signature = base64.b64encode(digest).decode("utf-8")

    # Debug logs for verification
    print("[BOKUN DEBUG] Date:", date_str)
    print("[BOKUN DEBUG] Message:", message)
    print("[BOKUN DEBUG] Signature:", signature)

    return signature

def millis_to_iso(ms: int) -> str:
    """Convert milliseconds since epoch to ISO 8601 string."""

    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.isoformat()


def normalize_start_time(slot: Dict[str, Any]) -> Optional[str]:
    """Return the best available ISO-8601 start time for a slot."""

    def _coerce(value: Any) -> Optional[str]:
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return millis_to_iso(int(value))

        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return None

            # Bókun often returns timestamps with "Z" or "+0000" suffixes.
            cleaned = cleaned.replace("Z", "+00:00")
            if cleaned.endswith("+0000"):
                cleaned = cleaned[:-5] + "+00:00"

            try:
                # datetime.fromisoformat handles most ISO 8601 combinations.
                parsed = datetime.fromisoformat(cleaned)
            except ValueError:
                # If parsing fails, fall back to raw string – FullCalendar can still render it.
                return value

            # Ensure timezone awareness so the frontend renders the correct absolute time.
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)

            return parsed.isoformat()

        return None

    for key in ("startTimeUtc", "startTime", "localStartTime", "date"):
        normalized = _coerce(slot.get(key))
        if normalized:
            return normalized

    return None

# --- Bokun API Request ---

def _build_request_headers(method: str, path: str, query: str) -> Dict[str, str]:
    """Create Bokun request headers including a fresh signature."""

    date_str = bokun_date_str()
    signature = generate_signature(SECRET_KEY, ACCESS_KEY, date_str, method, path, query)

    return {
        "X-Bokun-Date": date_str,
        "X-Bokun-AccessKey": ACCESS_KEY,
        "X-Bokun-Signature": signature,
        "Accept": "application/json",
    }


def _build_events(product: Product, slots: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Transform raw Bokun slots into FullCalendar-compatible events."""

    events: List[Dict[str, Any]] = []

    for slot in slots:
        spots = slot.get("availabilityCount", 0)
        is_sold_out = slot.get("soldOut", False) or slot.get("unavailable", False)
        start_time = normalize_start_time(slot)

        events.append(
            {
                "title": f"{product.name} - {spots} spots",
                "start": start_time,
                "color": "green" if not is_sold_out else "red",
                "url": product.booking_url if not is_sold_out else None,
            }
        )

    return events


def get_availability_for_products(start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """Fetch availability for each product and return FullCalendar event payloads."""

    events: List[Dict[str, Any]] = []

    for product in PRODUCTS:
        method = "GET"
        path = f"/activity.json/{product.id}/availabilities"
        query = f"?start={start_date}&end={end_date}&lang=EN&currency=ISK&includeSoldOut=false"
        full_path = path + query

        headers = _build_request_headers(method, path, query)

        url = "https://api.bokun.io" + full_path
        print("[BOKUN DEBUG] Request URL:", url)

        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:  # pragma: no cover - side effect logging only
            print("[ERROR] Request failed for", product.id, ":", exc)
            continue

        events.extend(_build_events(product, data))

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
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Railway sets PORT automatically
    print(f"[INFO] Starting Flask on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=True)

