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

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# --- Flask setup ---
app = Flask(__name__)
CORS(app)

# --- Bókun API keys ---
ACCESS_KEY = os.environ.get("BOKUN_ACCESS_KEY", "75dd7122985a493ebcb1c04841ca2d17")
SECRET_KEY = os.environ.get("BOKUN_SECRET_KEY", "00c39fd375af4b8e8888b483d14335f5")

@dataclass(frozen=True)
class Product:
    """Small container describing a Bokun product we want to expose."""
    id: str
    name: str
    booking_url: str
    color: str = "green"
    duration_minutes: int = 120
    departure_location: str = "Portstewart/Portrush"


# --- Products you want to display ---
PRODUCTS: List[Product] = [
    Product(
        id="1084194",
        name="Skerries & Dunluce",
        booking_url="https://aquaholics.co.uk/pages/boku-test",
        color="#10b981",
        duration_minutes=120,
        departure_location="Portstewart/Portrush"
    ),
    Product(
        id="1087988",
        name="Giant's Causeway, Skerries & Dunluce",
        booking_url="https://aquaholics.co.uk/pages/giants-causeway-bkuk",
        color="#3b82f6",
        duration_minutes=180,
        departure_location="Portstewart/Portrush"
    ),
]

# --- Bokun Signature Helpers ---

def bokun_date_str() -> str:
    """Return UTC date s
