import os
from dotenv import load_dotenv
load_dotenv()
print(f"TOKEN: {os.getenv('CREATOR_BOT_TOKEN')}")
print(f"CREATOR_ID: {os.getenv('CREATOR_ID')}")
