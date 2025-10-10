"""Production Flask application exposing Bokun availability as FullCalendar events."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import requests
from flask import Flask, jsonify
from flask_cors import CORS

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

ACCESS_KEY = os.environ.get("BOKUN_ACCESS_KEY", "75dd7122985a493ebcb1c04841ca2d17")
SECRET_KEY = os.environ.get("BOKUN_SECRET_KEY", "00c39fd375af4b8e8888b483d14335f5")

@dataclass(frozen=True)
class Product:
    id: str
    name: str
    booking_url: str
    color: str = "green"
    duration_minutes: int = 120
    departure_location: str = "Portstewart/Portrush"

PRODUCTS: List[Product] = [
    Product(
        id="1084194",
        name="Skerries & Dunluce",
        booking_url="https://aquaholics.co.uk/pages/boku-test",
        color="#10b981",
        duration_minutes=90,
        departure_location="Portstewart/Portrush"
    ),
    Product(
        id="1087988",
        name="Giant's Causeway, Skerries & Dunluce",
        booking_url="https://aquaholics.co.uk/pages/giants-causeway-bkuk",
        color="#3b82f6",
        duration_minutes=150,
        departure_location="Portstewart/Portrush"
    ),
]

def bokun_date_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def generate_signature(secret_key: str, access_key: str, date_str: str, method: str, path: str, query: str = "") -> str:
    message = f"{date_str}{access_key}{method}{path}{query}".strip()
    digest = hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")

def millis_to_iso(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.isoformat()

def normalize_start_time(slot: Dict[str, Any]) -> Optional[str]:
    for key in ("startTimeUtc", "startTime"):
        value = slot.get(key)
        if isinstance(value, (int, float)) and value > 1000000000:
            return millis_to_iso(int(value))

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
                return parsed.isoformat()
            except ValueError:
                continue

    date_val = slot.get("date")
    time_val = None
    
    for time_key in ("startTime", "localStartTime", "time"):
        time_val = slot.get(time_key)
        if time_val:
            break
    
    if date_val:
        if isinstance(date_val, str):
            date_str = date_val.strip()[:10]
        elif isinstance(date_val, (int, float)):
            date_str = datetime.fromtimestamp(date_val / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        else:
            return None
        
        if time_val and isinstance(time_val, str):
            time_str = time_val.strip()
            if len(time_str) == 5:
                time_str += ":00"
            return f"{date_str}T{time_str}+00:00"
        elif time_val and isinstance(time_val, (int, float)):
            return millis_to_iso(int(time_val))
        
        return f"{date_str}T12:00:00+00:00"

    return None

def _build_request_headers(method: str, path: str, query: str) -> Dict[str, str]:
    date_str = bokun_date_str()
    signature = generate_signature(SECRET_KEY, ACCESS_KEY, date_str, method, path, query)
    return {
        "X-Bokun-Date": date_str,
        "X-Bokun-AccessKey": ACCESS_KEY,
        "X-Bokun-Signature": signature,
        "Accept": "application/json",
    }

def _build_events(product: Product, slots: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for slot in slots:
        spots = slot.get("availabilityCount", 0)
        is_sold_out = slot.get("soldOut", False) or slot.get("unavailable", False)
        start_time = normalize_start_time(slot)
        if not start_time:
            continue
        hours = product.duration_minutes // 60
        minutes = product.duration_minutes % 60
        if minutes > 0:
            duration_str = f"{hours}h {minutes}m"
        else:
            duration_str = f"{hours}h"
        events.append({
            "title": f"{product.name}",
            "start": start_time,
            "color": "#ef4444" if is_sold_out else product.color,
            "url": product.booking_url if not is_sold_out else None,
            "extendedProps": {
                "spots": spots,
                "soldOut": is_sold_out,
                "productName": product.name,
                "duration": duration_str,
                "durationMinutes": product.duration_minutes,
                "departureLocation": product.departure_location
            }
        })
    return events

def get_availability_for_products(start_date: str, end_date: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for product in PRODUCTS:
        method = "GET"
        path = f"/activity.json/{product.id}/availabilities"
        query = f"?start={start_date}&end={end_date}&lang=EN&currency=GBP&includeSoldOut=false"
        full_path = path + query
        headers = _build_request_headers(method, path, query)
        url = "https://api.bokun.io" + full_path
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            product_events = _build_events(product, data)
            events.extend(product_events)
            logger.info(f"Loaded {len(product_events)} events for {product.name}")
        except requests.RequestException as exc:
            logger.error(f"Request failed for {product.id}: {exc}")
            continue
    return events

@app.route("/")
def index():
    return jsonify({"status": "ok", "service": "Bokun Calendar API", "products": len(PRODUCTS)})

@app.route("/availability/<start>/<end>")
def availability(start, end):
    try:
        events = get_availability_for_products(start, end)
        logger.info(f"Returning {len(events)} total events for {start} to {end}")
        return jsonify(events)
    except Exception as e:
        logger.error(f"Error processing request: {e}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting Flask on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=True)
