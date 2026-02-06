from flask import Flask
from threading import Thread
import os
import time
import requests
import logging

# Configure logging: INFO for this script, ERROR for libraries
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Mute 'werkzeug' logger (Flask server logs)
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.setLevel(logging.ERROR)

# Mute 'urllib3' (used by requests) just in case
logging.getLogger('urllib3').setLevel(logging.ERROR)

app = Flask('')

@app.route('/')
def home():
    return "I am alive"

def run():
    # Bind to the port provided by the hosting env (e.g., Render)
    port = int(os.environ.get("PORT", 8080))
    try:
        app.run(host='0.0.0.0', port=port)
    except Exception as e:
        logging.error(f"Flask keep-alive server failed to start on port {port}: {e}")
        # Try a fallback port if 8080 is blocked and we are local
        if port == 8080:
             try:
                 logging.info("Attempting fallback port 8081...")
                 app.run(host='0.0.0.0', port=8081)
             except Exception:
                 logging.error("Fallback failed. Proceeding without keep-alive server.")

def ping_job(url=None):
    if not url:
        # Load from env or fallback
        url = os.environ.get("PING_URL", "https://bedorme-ydk8.onrender.com")
        
    while True:
        try:
            logging.info(f"Pinging {url}...")
            requests.get(url, timeout=10)
        except Exception as e:
            logging.error(f"Ping failed: {e}")
        time.sleep(7 * 60) # 7 minutes

def start_pinger(url=None):
    p = Thread(target=ping_job, args=(url,))
    p.daemon = True
    p.start()

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()
    
    start_pinger()
