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
    app.run(host='0.0.0.0', port=port)

def ping_job():
    url = "https://bedorme-1hb2.onrender.com"
    while True:
        try:
            logging.info(f"Pinging {url}...")
            requests.get(url, timeout=10)
        except Exception as e:
            logging.error(f"Ping failed: {e}")
        time.sleep(7 * 60) # 7 minutes

def keep_alive():
    t = Thread(target=run)
    t.start()
    
    p = Thread(target=ping_job)
    p.start()
