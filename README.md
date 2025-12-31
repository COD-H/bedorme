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

## Usage
- Start a chat with your Telegram bot.
- Use the provided commands to register, browse menus, place orders, and track deliveries.
- Admins and deliverers have access to additional management commands.

## Contributing
Contributions are welcome! Please open issues or submit pull requests for improvements and bug fixes.

## License
This project is licensed under the MIT License.
