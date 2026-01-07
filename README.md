# Requirements

To run the BeDormeDelivery server, you need:

- **Python Version:** Python 3.8 or higher
- **Python Packages:**
	- python-telegram-bot
	- python-dotenv
	- asyncio (included in Python 3.4+)
	- sqlite3 (included in Python standard library)

You can install the required packages using:
```bash
pip install -r requirements.txt
```

**requirements.txt example:**
```
python-telegram-bot>=20.0
python-dotenv>=1.0
```

- **Other Requirements:**
	- A Telegram Bot Token (set in a .env file)
	- Internet connection for Telegram API

# BeDormeDelivery
its a python code for a telegram bot for food delivery 

# BeDormeDelivery

BeDormeDelivery is a professional Python-based Telegram bot designed to streamline food delivery services for dormitory residents. The bot connects users with local restaurants, enables easy ordering, and coordinates delivery directly to dorm blocks, providing a seamless and efficient food delivery experience.

## Features
- **User-Friendly Ordering:** Browse menus from multiple restaurants and place orders directly through Telegram.
- **Location Integration:** Select your dorm block and room for precise delivery.
- **Order Tracking:** Track the status of your order and receive real-time updates.
- **Admin & Deliverer Tools:** Admins can manage orders, assign deliverers, and verify deliveries. Deliverers receive notifications and order details.
- **Secure Payment:** Users are guided through a secure payment process, including proof of payment upload.
- **Database Integration:** All user and order data are managed with SQLite for reliability and easy access.

## Technologies Used
- Python 3
- [python-telegram-bot](https://python-telegram-bot.org/)
- SQLite3
- asyncio

## Project Structure
- `bedorme.py` — Main bot logic and Telegram handlers
- `database.py` — Database models and operations
- `menus.py` — Restaurant menus and pricing
- `locations.py` — Restaurant and dorm block locations
- `view_db.py` — Utility to view database tables

## Getting Started
1. **Clone the repository:**
	```bash
	git clone <repo-url>
	cd bedorme
	```
2. **Install dependencies:**
	```bash
	pip install python-telegram-bot python-dotenv
	```
3. **Set up environment variables:**
	Create a `.env` file with your Telegram bot token and other required settings.
4. **Initialize the database:**
	Run the database initialization function in `database.py` or let the bot create tables on first run.
5. **Start the bot:**
	```bash
	python bedorme.py
	```

## Deploying to Render

- Create a new Web Service in Render using this repo. The included `render.yaml` configures:
	- `buildCommand`: `pip install -r requirements.txt`
	- `startCommand`: `python bedorme.py`
	- `healthCheckPath`: `/` (served by the small Flask keep-alive in `keep_alive.py`)
	- `PYTHON_VERSION`: `3.11.6` (recommended for python-telegram-bot)

- Set the following environment variables in the Render dashboard:
	- `TELEGRAM_TOKEN`: your bot token from BotFather
	- `ADMIN_CHAT_ID`: Telegram chat ID for your admin group (negative for supergroups)
	- `COMPLETED_ORDERS_CHANNEL_ID`: Channel ID for completion logs (optional but recommended)

Notes
- Web Service works with polling because `keep_alive.py` binds to the `$PORT` Render provides.
- If you prefer a Worker instead of a Web Service, you can create a Render Worker and use the same `startCommand` (`python bedorme.py`). The keep-alive server isn’t required for Workers.
- On startup, the bot clears any existing webhook to avoid conflicts with polling.

## Usage
- Start a chat with your Telegram bot.
- Use the provided commands to register, browse menus, place orders, and track deliveries.
- Admins and deliverers have access to additional management commands.

## Contributing
Contributions are welcome! Please open issues or submit pull requests for improvements and bug fixes.

## License
This project is licensed under the MIT License.
