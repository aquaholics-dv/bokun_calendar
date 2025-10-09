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

    return signature

def millis_to_iso(ms: int) -> str:
    """Convert milliseconds since epoch to ISO 8601 string."""
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.isoformat()


def normalize_start_time(slot: Dict[str, Any]) -> Optional[str]:
    """Return the best available ISO-8601 start time for a slot."""
    
    # Print raw slot data for debugging
    print(f"[DEBUG] Raw slot keys: {list(slot.keys())}")
    print(f"[DEBUG] Slot data: {slot}")

    # Try millisecond timestamps first (most reliable)
    for key in ("startTimeUtc", "startTime"):
        value = slot.get(key)
        if isinstance(value, (int, float)) and value > 1000000000:  # Reasonable timestamp
            result = millis_to_iso(int(value))
            print(f"[DEBUG] Using {key}={value} -> {result}")
            return result

    # Try full ISO datetime strings
    for key in ("startTimeUtc", "startTime", "localStartTime"):
        value = slot.get(key)
        if isinstance(value, str) and len(value) > 10:
            cleaned = value.strip().replace("Z", "+00:00")
            if cleaned.endswith("+0000"):
                cleaned = cleaned[:-5] + "+00:00"
            try:
                parsed = datetime.fromisoformat(cleaned)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                result = parsed.isoformat()
                print(f"[DEBUG] Using {key}={value} -> {result}")
                return result
            except ValueError:
                continue

    # Try combining date + time fields
    date_val = slot.get("date")
    time_val = None
    
    # Look for time in various fields
    for time_key in ("startTime", "localStartTime", "time"):
        time_val = slot.get(time_key)
        if time_val:
            break
    
    print(f"[DEBUG] date={date_val}, time={time_val}")
    
    if date_val:
        # Handle date as string
        if isinstance(date_val, str):
            date_str = date_val.strip()[:10]  # Get YYYY-MM-DD part
        # Handle date as milliseconds
        elif isinstance(date_val, (int, float)):
            date_str = datetime.fromtimestamp(date_val / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        else:
            print(f"[WARNING] Unknown date type: {type(date_val)}")
            return None
        
        # Handle time
        if time_val:
            if isinstance(time_val, str):
                time_str = time_val.strip()
                # Ensure HH:MM:SS format
                if len(time_str) == 5:  # HH:MM
                    time_str += ":00"
                result = f"{date_str}T{time_str}+00:00"
                print(f"[DEBUG] Combined date+time -> {result}")
                return result
            elif isinstance(time_val, (int, float)):
                # Time as milliseconds
                result = millis_to_iso(int(time_val))
                print(f"[DEBUG] Using time milliseconds -> {result}")
                return result
        
        # No time found, default to noon (more visible than midnight)
        result = f"{date_str}T12:00:00+00:00"
        print(f"[DEBUG] Date only, defaulting to noon -> {result}")
        return result

    print("[WARNING] No valid date/time found in slot")
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

    for i, slot in enumerate(slots):
        spots = slot.get("availabilityCount", 0)
        is_sold_out = slot.get("soldOut", False) or slot.get("unavailable", False)
        
        print(f"\n[DEBUG] === Processing slot {i} for {product.name} ===")
        start_time = normalize_start_time(slot)

        if not start_time:
            print(f"[WARNING] Skipping slot {i} - no valid start time")
            continue

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
        print(f"\n[BOKUN DEBUG] === Fetching {product.name} ===")
        print(f"[BOKUN DEBUG] Request URL: {url}")

        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            print(f"[BOKUN DEBUG] Received {len(data)} slots from Bokun")
        except requests.RequestException as exc:
            print(f"[ERROR] Request failed for {product.id}: {exc}")
            continue

        events.extend(_build_events(product, data))

    print(f"\n[BOKUN DEBUG] === Total events generated: {len(events)} ===\n")
    return events

# --- Flask route for frontend ---

@app.route("/availability/<start>/<end>")
def availability(start, end):
    try:
        events = get_availability_for_products(start, end)
        return jsonify(events)
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# --- Run Flask locally or on Railway ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[INFO] Starting Flask on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=True)
