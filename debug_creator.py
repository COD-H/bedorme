import logging
import os
from dotenv import load_dotenv
from creator_bot import create_creator_app

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)

def main():
    print("Testing Creator Bot Startup...")
    token = os.getenv("CREATOR_BOT_TOKEN")
    print(f"Token found: {token[:10]}...{token[-5:] if token else ''}")
    
    try:
        app = create_creator_app()
        if not app:
            print("Error: create_creator_app() returned None")
            return
        
        print("Application built successfully. Starting polling...")
        app.run_polling(timeout=10) # Run for a bit and then stop? No, it blocks.
    except Exception as e:
        print(f"CRASH during startup: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
