diff --git a/app.py b/app.py
index 8ca5b76353f6661dece271478a5768a573fbed8a..c27bb980f4aa8818c2a51c92788d8d1a63faae55 100644
--- a/app.py
+++ b/app.py
@@ -1,116 +1,136 @@
 from flask import Flask, jsonify
 from flask_cors import CORS
 import requests, hmac, hashlib, base64, os
 from datetime import datetime, timezone
+from zoneinfo import ZoneInfo
 
 # --- Flask setup ---
 app = Flask(__name__)
 CORS(app)  # Allow CORS so Shopify can fetch data
 
 # --- Bókun API keys (replace if needed) ---
 ACCESS_KEY = "75dd7122985a493ebcb1c04841ca2d17"
 SECRET_KEY = "00c39fd375af4b8e8888b483d14335f5"
 
 # --- Products you want to display ---
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
 
 # --- Bokun Signature Helpers ---
 
 def bokun_date_str():
     """Return UTC date string exactly as Bokun expects."""
     return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
 
 def generate_signature(secret_key, access_key, date_str, method, path, query=""):
     """Generate signature identical to Bokun Postman pre-request script."""
     message = f"{date_str}{access_key}{method}{path}{query}".strip()
     digest = hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha1).digest()
     signature = base64.b64encode(digest).decode("utf-8")
 
     # Debug logs for verification
     print("[BOKUN DEBUG] Date:", date_str)
     print("[BOKUN DEBUG] Message:", message)
     print("[BOKUN DEBUG] Signature:", signature)
 
     return signature
 
-def millis_to_iso(ms):
-    """Convert milliseconds since epoch to ISO 8601 string."""
-    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
-    return dt.isoformat()
+DISPLAY_TIMEZONE = ZoneInfo(os.environ.get("CALENDAR_TIMEZONE", "Europe/London"))
+
+
+def millis_to_local_dt(ms):
+    """Convert milliseconds since epoch to timezone-aware datetime for display."""
+    utc_dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
+    return utc_dt.astimezone(DISPLAY_TIMEZONE)
 
 # --- Bokun API Request ---
 
 def get_availability_for_products(start_date, end_date):
     events = []
 
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
-                start_time = millis_to_iso(slot["date"]) if "date" in slot else None
+                start_dt = millis_to_local_dt(slot["date"]) if "date" in slot else None
+
+                if not start_dt:
+                    continue
+
+                time_label = start_dt.strftime("%H:%M")
+                date_label = start_dt.strftime("%d %b %Y")
 
                 events.append({
-                    "title": f"{product['name']} - {spots} spots",
-                    "start": start_time,
-                    "color": "green" if not is_sold_out else "red",
+                    "id": f"{product_id}-{slot.get('id', slot.get('date'))}",
+                    "title": product["name"],
+                    "start": start_dt.isoformat(),
                     "url": booking_url if not is_sold_out else None,
+                    "spots": spots,
+                    "productName": product["name"],
+                    "timeLabel": time_label,
+                    "dateLabel": date_label,
+                    "spotsLabel": "Sold out" if is_sold_out else f"{spots} spot{'s' if spots != 1 else ''} available",
+                    "isSoldOut": is_sold_out,
+                    "className": [
+                        "bk-event",
+                        "bk-event--sold-out" if is_sold_out else "bk-event--available",
+                    ],
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
 if __name__ == "__main__":
     port = int(os.environ.get("PORT", 5000))  # Railway sets PORT automatically
     print(f"[INFO] Starting Flask on port {port}...")
     app.run(host="0.0.0.0", port=port, debug=True)
