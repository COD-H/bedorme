import os
import logging
import sqlite3
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

import logging
import os
import sqlite3
import time
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from dotenv import load_dotenv
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

load_dotenv()

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# CONFIG
TOKEN = os.getenv("bedorme_creator_bot_token")
DB_PATH = os.path.join(os.path.dirname(__file__), 'bedorme.db') # Same DB
MAPS_URL = "https://www.google.com/maps/search/?api=1&query={},{}"

def get_db_connection():
    return sqlite3.connect(DB_PATH)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"👑 Welcome Creator {user.first_name}!\n\n"
        "Commands:\n"
        "/active - See live deliveries\n"
        "/orders - Recent orders\n"
        "/stats - View Statistics & Profit\n"
        "/user <id> - User details & history\n"
        "/deepdive <order_id> - Generate Full PDF Report",
         reply_markup=ReplyKeyboardMarkup([
            ["/active", "/orders", "/stats"]
        ], resize_keyboard=True)
    )

def format_order(row):
    # order_id, customer_id, deliverer_id, restaurant, items, total_price, status, code, mid_proof, proof_ts, del_proof, del_lat, del_lon, pickup_lat, pickup_lon, created_at, delivered_at
    oid = row[0]
    cust_id = row[1]
    status = row[6]
    rest = row[3]
    price = row[5]
    return f"📦 #{oid} | {status.upper()} | {rest} | {price} ETB | User: {cust_id}"

async def list_active_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE status IN ('pending', 'accepted', 'picked_up')")
    orders = cur.fetchall()
    conn.close()

    if not orders:
        await update.message.reply_text("No active orders right now.")
        return

    msg = "🚀 **Active Deliveries:**\n\n"
    keyboard = []
    
    for order in orders:
        msg += format_order(order) + "\n"
        keyboard.append([InlineKeyboardButton(f"View #{order[0]}", callback_data=f"view_{order[0]}")])
    
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def list_recent_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders ORDER BY order_id DESC LIMIT 10")
    orders = cur.fetchall()
    conn.close()

    if not orders:
        await update.message.reply_text("No orders found.")
        return

    msg = "📜 **Recent Orders:**\n\n"
    keyboard = []
    for order in orders:
        msg += format_order(order) + "\n"
        keyboard.append([InlineKeyboardButton(f"View #{order[0]}", callback_data=f"view_{order[0]}")])
        
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def order_details_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if not data.startswith("view_"):
        return
        
    order_id = int(data.split("_")[1])
    
    conn = get_db_connection()
    cur = conn.cursor()
    # Get Order
    cur.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    order = cur.fetchone()
    
    if not order:
        await query.edit_message_text("Order not found.")
        conn.close()
        return
        
    # Get User
    cust_id = order[1]
    cur.execute("SELECT * FROM users WHERE user_id = ?", (cust_id,))
    user = cur.fetchone()
    
    conn.close()
    
    # Unpack Order
    # 0:id, 1:cust, 2:deliv, 3:rest, 4:items, 5:price, 6:stat, 7:code, 8:mid_p, 9:ts, 10:del_p, 11:d_lat, 12:d_lon, 13:p_lat, 14:p_lon, 15:created, 16:delivered
    
    status = order[6]
    created_ts = order[15]
    del_ts = order[16]
    
    created_str = time.ctime(created_ts) if created_ts else "N/A"
    del_str = time.ctime(del_ts) if del_ts else "Not yet"
    duration = f"{round((del_ts - created_ts)/60, 1)} min" if (created_ts and del_ts) else "N/A"
    
    user_name = user[1] if user else "Unknown"
    user_phone = user[5] if user else "Unknown"
    
    text = (
        f"📦 **Details for Order #{order_id}**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 **Customer:** {user_name} (`{cust_id}`)\n"
        f"📞 **Phone:** {user_phone}\n"
        f"🍴 **Restaurant:** {order[3]}\n"
        f"🍔 **Items:** {order[4]}\n"
        f"💰 **Total:** {order[5]} ETB\n"
        f"📊 **Status:** {status.upper()}\n"
        f"🔐 **Code:** {order[7]}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏰ **Created:** {created_str}\n"
        f"🏁 **Delivered:** {del_str}\n"
        f"⏱ **Duration:** {duration}\n"
    )
    
    buttons = []
    # Location Buttons if available
    if order[13] and order[14]: # Pickup
        url = MAPS_URL.format(order[13], order[14])
        buttons.append([InlineKeyboardButton("📍 Pickup Location (Rest)", url=url)])
        
    if order[11] and order[12]: # Delivery
        url = MAPS_URL.format(order[11], order[12])
        buttons.append([InlineKeyboardButton("📍 Delivery Location (User)", url=url)])
        
    buttons.append([InlineKeyboardButton("📄 Deep Dive PDF", callback_data=f"deep_{order_id}")])
        
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

async def user_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /user <telegram_id>")
        return
        
    user_id = args[0]
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cur.fetchone()
    
    if not user:
        await update.message.reply_text("User not found.")
        conn.close()
        return
        
    # Get History
    cur.execute("SELECT * FROM user_history WHERE user_id = ? ORDER BY change_timestamp DESC", (user_id,))
    history = cur.fetchall()
    
    conn.close()
    
    msg = (
        f"👤 **User Profile: {user[1]}**\n"
        f"ID: `{user[0]}`\n"
        f"Username: @{user[2]}\n"
        f"Phone: {user[5]}\n"
        f"Student ID: {user[8]}\n" # Assuming index
        f"Block/Dorm: {user[3]}/{user[4]}\n"
        f"Gender: {user[6]}\n"
        f"Language: {user[10]}\n\n"
    )
    
    if history:
        msg += "📜 **Registration History:**\n"
        for h in history:
            # history schema: id, user_id, old_name, old_user, old_phone, old_sid, old_blk, old_dorm, old_gender, ts
            date = time.ctime(h[9])
            msg += f"📅 {date}:\n"
            if h[2]: msg += f" - Name was: {h[2]}\n"
            if h[4]: msg += f" - Phone was: {h[4]}\n"
            
    await update.message.reply_text(msg, parse_mode='Markdown')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    
    now = time.time()
    week_ago = now - (7 * 24 * 60 * 60)
    month_ago = now - (30 * 24 * 60 * 60)
    
    # Week Stats
    cur.execute("SELECT COUNT(*), SUM(total_price) FROM orders WHERE created_at > ? AND status='complete'", (week_ago,))
    week_stats = cur.fetchone()
    week_count = week_stats[0] or 0
    week_rev = week_stats[1] or 0
    
    # Month Stats
    cur.execute("SELECT COUNT(*), SUM(total_price) FROM orders WHERE created_at > ? AND status='complete'", (month_ago,))
    month_stats = cur.fetchone()
    month_count = month_stats[0] or 0
    month_rev = month_stats[1] or 0
    
    # Canceled
    cur.execute("SELECT COUNT(*) FROM orders WHERE status='cancelled'")
    cancel_count = cur.fetchone()[0]
    
    conn.close()
    
    # Assume 10% commission for profit calc (Customize this!)
    commission_rate = 0.10 
    week_profit = week_rev * commission_rate
    month_profit = month_rev * commission_rate
    
    msg = (
        "📊 **Business Statistics**\n\n"
        "📅 **Last 7 Days:**\n"
        f" - Orders: {week_count}\n"
        f" - Transferred: {week_rev:.2f} ETB\n"
        f" - Profit (est. 10%): {week_profit:.2f} ETB\n\n"
        "📅 **Last 30 Days:**\n"
        f" - Orders: {month_count}\n"
        f" - Transferred: {month_rev:.2f} ETB\n"
        f" - Profit (est. 10%): {month_profit:.2f} ETB\n\n"
        "🚫 **Total Cancelled:** {cancel_count}"
    )
    
    await update.message.reply_text(msg.format(cancel_count=cancel_count), parse_mode='Markdown')

async def deep_dive_pdf_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Generating PDF...", cache_time=0)
    
    data = query.data
    order_id = int(data.split("_")[1])
    
    # Fetch Data
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    order = cur.fetchone()
    
    cust_id = order[1]
    cur.execute("SELECT * FROM users WHERE user_id = ?", (cust_id,))
    user = cur.fetchone()
    conn.close()
    
    # Generate PDF
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()
    
    # Title
    elements.append(Paragraph(f"Order Deep Dive Report - #{order_id}", styles['Title']))
    elements.append(Spacer(1, 12))
    
    # Data Preparation
    created_date = time.ctime(order[15]) if order[15] else "N/A"
    
    data = [
        ["Field", "Value"],
        ["Order ID", str(order_id)],
        ["Date", created_date],
        ["Status", order[6].upper()],
        ["Restaurant", order[3]],
        ["Items", order[4]],
        ["Total Amount", f"{order[5]} ETB"],
        ["Customer Name", user[1] if user else "Unknown"],
        ["Customer ID", str(cust_id)],
        ["Phone", user[5] if user else "Unknown"],
        ["Dormitory", f"{user[3]}/{user[4]}" if user else "Unknown"],
        ["Verification Code", order[7]],
    ]
    
    t = Table(data)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    elements.append(t)
    
    # TODO: Add Images (Receipts) if stored as files locally or download from telegram ID
    # Since we store file_ids, we'd need to fetch them from Telegram servers which requires bot API
    # For now, just data.
    
    doc.build(elements)
    buffer.seek(0)
    
    await context.bot.send_document(
        chat_id=query.message.chat_id,
        document=buffer,
        filename=f"order_{order_id}_deep_dive.pdf",
        caption=f"Deep Dive Report for Order #{order_id}"
    )


def main():
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("active", list_active_orders))
    application.add_handler(CommandHandler("orders", list_recent_orders))
    application.add_handler(CommandHandler("user", user_details))
    application.add_handler(CommandHandler("stats", stats_command))
    
    application.add_handler(CallbackQueryHandler(order_details_callback, pattern='^view_'))
    application.add_handler(CallbackQueryHandler(deep_dive_pdf_callback, pattern='^deep_'))

    print("Creator Bot Started...")
    application.run_polling()

if __name__ == "__main__":
    main()
# You might need to change this if your detailed logic is elsewhere

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome, Creator.\n\n"
        "Commands:\n"
        "/orders - List all orders\n"
        "/active - List active/ongoing orders\n"
        "/user <id> - Get user details & history\n"
        "/stats - Database statistics"
    )

async def list_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_filter = context.args[0] if context.args else None
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    if status_filter:
        cur.execute("SELECT * FROM orders WHERE status = ? ORDER BY order_id DESC LIMIT 20", (status_filter,))
    else:
        cur.execute("SELECT * FROM orders ORDER BY order_id DESC LIMIT 20")
    
    orders = cur.fetchall()
    conn.close()
    
    if not orders:
        await update.message.reply_text("No orders found.")
        return

    text = "📋 **Recent Orders**\n\n"
    keyboard = []
    
    for row in orders:
        status_emoji = "✅" if row['status'] == 'complete' else "⏳" if row['status'] == 'pending' else "🏃"
        text += f"#{row['order_id']} | {status_emoji} {row['status']} | {row['restaurant']} -> {row['total_price']} ETB\n"
        keyboard.append([InlineKeyboardButton(f"View Order #{row['order_id']}", callback_data=f"view_order_{row['order_id']}")])

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def list_active_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE status NOT IN ('complete', 'cancelled') ORDER BY order_id DESC")
    orders = cur.fetchall()
    conn.close()

    if not orders:
        await update.message.reply_text("No active orders.")
        return

    text = "🏃 **Ongoing Deliveries**\n\n"
    keyboard = []
    
    for row in orders:
        text += f"#{row['order_id']} | {row['restaurant']} | {row['status']}\n"
        keyboard.append([InlineKeyboardButton(f"Managed Order #{row['order_id']}", callback_data=f"view_order_{row['order_id']}")])

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def view_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    order_id = int(query.data.split("_")[2])
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    order = cur.fetchone()
    
    if not order:
        await query.edit_message_text("Order not found.")
        conn.close()
        return

    # Get Customer info
    cur.execute("SELECT * FROM users WHERE user_id = ?", (order['customer_id'],))
    customer = cur.fetchone()
    
    conn.close()
    
    created_ts = order['created_at'] if 'created_at' in order.keys() and order['created_at'] else None
    delivered_ts = order['delivered_at'] if 'delivered_at' in order.keys() and order['delivered_at'] else None
    
    created_str = datetime.datetime.fromtimestamp(created_ts).strftime('%Y-%m-%d %H:%M:%S') if created_ts else "N/A"
    delivered_str = datetime.datetime.fromtimestamp(delivered_ts).strftime('%Y-%m-%d %H:%M:%S') if delivered_ts else "Pending"
    
    duration = "N/A"
    if created_ts and delivered_ts:
        diff = delivered_ts - created_ts
        duration = str(datetime.timedelta(seconds=int(diff)))

    details = (
        f"📦 **Order #{order['order_id']} Detail**\n"
        f"Status: {order['status']}\n"
        f"Restaurant: {order['restaurant']}\n"
        f"Items: {order['items']}\n"
        f"Price: {order['total_price']} ETB\n\n"
        f"👤 **Customer:** {customer['name'] if customer else 'Unknown'} (ID: {order['customer_id']})\n"
        f"📞 Phone: {customer['phone'] if customer else 'N/A'}\n"
        f"🏠 Loc: {customer['block']}/{customer['dorm_number'] if customer else '?'}\n\n"
        f"🕒 **Timeline:**\n"
        f"Created: {created_str}\n"
        f"Delivered: {delivered_str}\n"
        f"Duration: {duration}\n"
    )
    
    keyboard = []
    
    # Locations
    if order['pickup_lat'] and order['pickup_lon']:
        keyboard.append([InlineKeyboardButton("📍 Pickup Location (Rest.)", callback_data=f"loc_pickup_{order_id}")])
    
    if order['delivery_lat'] and order['delivery_lon']:
        keyboard.append([InlineKeyboardButton("📍 Delivery Location (User)", callback_data=f"loc_delivery_{order_id}")])

    await query.edit_message_text(details, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def location_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split("_")
    loc_type = data[1] # pickup or delivery
    order_id = int(data[2])
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT pickup_lat, pickup_lon, delivery_lat, delivery_lon, restaurant FROM orders WHERE order_id = ?", (order_id,))
    order = cur.fetchone()
    conn.close()
    
    if not order:
        return

    lat, lon = 0, 0
    label = ""
    
    if loc_type == 'pickup':
        lat, lon = order['pickup_lat'], order['pickup_lon']
        label = f"Restaurant: {order['restaurant']}"
    elif loc_type == 'delivery':
        lat, lon = order['delivery_lat'], order['delivery_lon']
        label = f"Delivery Location for Order #{order_id}"
        
    if lat and lon:
        await context.bot.send_location(chat_id=update.effective_chat.id, latitude=lat, longitude=lon)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=label)
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Location data not available.")

async def get_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /user <user_id>")
        return
        
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid User ID.")
        return
        
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Current Info
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cur.fetchone()
    
    if not user:
        await update.message.reply_text("User not found.")
        conn.close()
        return
        
    # History
    cur.execute("SELECT * FROM user_history WHERE user_id = ? ORDER BY change_timestamp DESC", (user_id,))
    history = cur.fetchall()
    
    conn.close()
    
    text = (
        f"👤 **User Info: {user['name']}**\n"
        f"ID: {user['user_id']}\n"
        f"Username: @{user['username']}\n"
        f"Phone: {user['phone']}\n"
        f"Student ID: {user['student_id']}\n"
        f"Dorm: {user['block']} / {user['dorm_number']}\n"
        f"Gender: {user['gender']}\n"
        f"Deliverer: {'Yes' if user['is_deliverer'] else 'No'}\n\n"
    )
    
    if history:
        text += "📜 **Registration History:**\n"
        for h in history:
            ts = datetime.datetime.fromtimestamp(h['change_timestamp']).strftime('%Y-%m-%d')
            text += f"- {ts}: prev. Name: {h['old_name']}, Phone: {h['old_phone']}\n"
    else:
        text += "No history of changes."
        
    await update.message.reply_text(text, parse_mode='Markdown')

def main():
    if not TOKEN:
        print("Error: CREATOR_BOT_TOKEN not found in environment.")
        return

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("orders", list_orders))
    application.add_handler(CommandHandler("active", list_active_orders))
    application.add_handler(CommandHandler("user", get_user_info))
    
    application.add_handler(CallbackQueryHandler(view_order_callback, pattern=r"^view_order_"))
    application.add_handler(CallbackQueryHandler(location_callback, pattern=r"^loc_"))

    print("Creator Bot Started...")
    application.run_polling()

if __name__ == '__main__':
    main()
