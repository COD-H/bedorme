import os
import logging
import sqlite3
import datetime
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    ContextTypes, MessageHandler, filters, TypeHandler,
    ApplicationHandlerStop, ConversationHandler
)
from dotenv import load_dotenv

# Import database functions
from database import (
    get_db_connection, get_user, ban_user, get_full_user_info, 
    add_cafe_contract, get_user_by_username
)
from menus import MENUS

load_dotenv()

TOKEN = os.getenv("bedorme_creator_bot_token")
CREATOR_ID_RAW = os.getenv("CREATOR_ID", "0")
try:
    CREATOR_ID = int(CREATOR_ID_RAW)
except ValueError:
    CREATOR_ID = 0

logger = logging.getLogger(__name__)

async def security_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Global security check for every update."""
    user = update.effective_user
    if not user:
        return

    if user.id != CREATOR_ID:
        # Unauthorized access attempt
        user_id = user.id
        username = user.username or "No Username"
        full_name = user.full_name or "Unknown Name"
        
        # Try to find more info from our database
        db_user = get_user(user_id)
        # Assuming database columns: user_id, username, name, student_id, block, dorm_number, phone, gender, is_deliverer, balance, tokens, language, is_banned
        # Phone is usually index 6
        phone = "Unknown"
        if db_user:
            try:
                # Check for phone column (index 6 typically)
                phone = db_user[6] if len(db_user) > 6 else "Not in DB"
            except:
                phone = "Error fetching"
        
        # Log the breach
        logger.warning(f"SECURITY BREACH: {full_name} (@{username}) ID: {user_id} tried to access Creator Bot.")
        
        # Alert the unauthorized user
        try:
            if not context.user_data.get('breach_alerted'):
                await update.effective_chat.send_message(
                    f"🚨 **SECURITY BREACH** 🚨\n\n"
                    f"Unauthorized access attempt logged for:\n"
                    f"**Account Name:** {full_name}\n"
                    f"**Username:** @{username}\n"
                    f"**Phone:** {phone}\n"
                    f"**User ID:** `{user_id}`\n\n"
                    "**SYSTEM ACTION:** You have been blacklisted and reported.",
                    parse_mode='Markdown'
                )
                context.user_data['breach_alerted'] = True
                
                # Ban the user from the main service
                ban_user(user_id)
        except Exception as e:
            logger.error(f"Error handling breach: {e}")

        # STOP all further processing for this update
        raise ApplicationHandlerStop

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command for Creator only (passed security_check already)."""
    # Reset breach flag just in case the creator was testing
    context.user_data['breach_alerted'] = False
    
    await update.message.reply_text(
        f"👑 **Welcome Creator**\n\n"
        "Security Shield: **ACTIVE** ✅\n"
        "All unauthorized inputs are being blocked.\n\n"
        "Commands:\n"
        "/active - See live deliveries\n"
        "/orders - Recent orders\n"
        "/stats - View System Statistics\n"
        "/investigate <id> - Deep search user database\n"
        "/user <id> - Quick user check",
        reply_markup=ReplyKeyboardMarkup([
            ["/active", "/orders", "/stats"]
        ], resize_keyboard=True),
        parse_mode='Markdown'
    )

async def investigate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /investigate <user_id>")
        return
    
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid ID format.")
        return
        
    data = get_full_user_info(target_id)
    if not data:
        await update.message.reply_text(f"No record found for ID: {target_id}")
        return
        
    u = data['info']
    history = data['history']
    orders = data['orders']
    
    # Map user fields: 0:id, 1:username, 2:name, 3:student_id, 4:block, 5:dorm, 6:phone, 7:gender, 8:is_deliverer, 9:balance, 10:tokens, 11:lang, 12:banned
    report = (
        f"🕵️ **CREATOR AUDIT: {u[2]}**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🆔 **ID:** `{u[0]}`\n"
        f"👤 **Username:** @{u[1]}\n"
        f"📞 **Phone:** {u[6]}\n"
        f"🎓 **Student ID:** {u[3]}\n"
        f"🏠 **Dorm:** Block {u[4]}, Room {u[5]}\n"
        f"🚻 **Gender:** {u[7]}\n"
        f"💰 **Balance:** {u[9]} ETB\n"
        f"💎 **Tokens:** {u[10]}\n"
        f"🚲 **Deliverer:** {'✅ Yes' if u[8] else '❌ No'}\n"
        f"🔴 **Banned:** {'🚨 YES' if (len(u) > 12 and u[12]) else '🟢 No'}\n"
    )
    
    if history:
        report += "\n📜 **Update History:**\n"
        for h in history[:5]: # Last 5 changes
            # h: 0:history_id, 1:user_id, 2:old_name, 3:old_username, 4:old_phone, 9:timestamp
            ts = datetime.datetime.fromtimestamp(h[9]).strftime('%Y-%m-%d %H:%M')
            report += f"- {ts}: {h[2]} (@{h[3]}) phone: {h[4]}\n"
            
    if orders:
        report += f"\n🛍️ **Past Orders ({len(orders)}):**\n"
        for o in orders[:8]:
            # o: order_id, customer_id, deliverer_id, restaurant, items, price, status...
            report += f"- #{o[0]} | {o[3]} | {o[5]} ETB | {o[6]}\n"
            
    await update.message.reply_text(report, parse_mode='Markdown')

async def list_active_orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE status IN ('pending', 'accepted', 'picked_up')")
    orders = cur.fetchall()
    conn.close()

    if not orders:
        await update.message.reply_text("No active orders.")
        return

    msg = "🚀 **Live Deliveries:**\n\n"
    keyboard = []
    for order in orders:
        msg += f"📦 #{order[0]} | {order[6].upper()} | {order[3]} | User: {order[1]}\n"
        keyboard.append([InlineKeyboardButton(f"View Order #{order[0]}", callback_data=f"view_{order[0]}")])
    
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    user_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM orders")
    order_count = cur.fetchone()[0]
    cur.execute("SELECT SUM(total_price) FROM orders WHERE status = 'complete'")
    total_rev = cur.fetchone()[0] or 0
    conn.close()
    
    await update.message.reply_text(
        f"📊 **System Stats**\n\n"
        f"👥 Users: {user_count}\n"
        f"📦 Total Orders: {order_count}\n"
        f"💰 Total Revenue: {total_rev:.2f} ETB",
        parse_mode='Markdown'
    )

WAITING_USERNAME, WAITING_PHONE, WAITING_NAME = range(3)

async def cafe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "🏪 **Available Cafes:**\n\n"
    keyboard = []
    for cafe in MENUS.keys():
        msg += f"📍 {cafe}\n"
        keyboard.append([InlineKeyboardButton(f"Add Contract for {cafe}", callback_data=f"contract_{cafe}")])
    
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def contract_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    cafe_name = query.data.replace("contract_", "")
    context.user_data['contract_cafe'] = cafe_name
    
    await query.edit_message_text(f"📝 Adding contract for **{cafe_name}**.\n\nPlease enter the user's **Telegram Username** (with or without @):", parse_mode='Markdown')
    return WAITING_USERNAME

async def process_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    user_id = get_user_by_username(username)
    
    if not user_id:
        await update.message.reply_text("❌ User not found in main bot database. They must be registered in the bot first. Please enter a valid username or /cancel:")
        return WAITING_USERNAME
    
    context.user_data['contract_user_id'] = user_id
    context.user_data['contract_username'] = username
    
    await update.message.reply_text("📱 Great! Now enter their **Phone Number**:")
    return WAITING_PHONE

async def process_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    context.user_data['contract_phone'] = phone
    
    await update.message.reply_text("👤 Almost done! Enter their **Full Name**:")
    return WAITING_NAME

async def process_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    full_name = update.message.text.strip()
    user_id = context.user_data['contract_user_id']
    cafe_name = context.user_data['contract_cafe']
    phone = context.user_data['contract_phone']
    username = context.user_data['contract_username']
    
    add_cafe_contract(user_id, cafe_name, phone, username, full_name)
    
    await update.message.reply_text(
        f"✅ **Contract Added Successfully!**\n\n"
        f"👤 **User:** {full_name} (@{username})\n"
        f"📍 **Cafe:** {cafe_name}\n"
        f"📞 **Phone:** {phone}\n"
        f"🆔 **User ID:** `{user_id}`",
        parse_mode='Markdown'
    )
    return ConversationHandler.END

async def cancel_contract(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Contract addition cancelled.")
    return ConversationHandler.END

def create_creator_app():
    if not TOKEN:
        return None

    application = Application.builder().token(TOKEN).build()

    # 1. SECURITY LAYER (GROUP -1 runs first)
    application.add_handler(TypeHandler(Update, security_check), group=-1)

    # 2. HANDLERS
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("investigate", investigate_command))
    application.add_handler(CommandHandler("user", investigate_command))
    application.add_handler(CommandHandler("active", list_active_orders_command))
    application.add_handler(CommandHandler("orders", list_active_orders_command)) # Reuse list_active for now or simple list
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("cafe", cafe_command))

    # Contract Conversation Handler
    contract_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(contract_callback, pattern="^contract_")],
        states={
            WAITING_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_username)],
            WAITING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_phone)],
            WAITING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_name)],
        },
        fallbacks=[CommandHandler("cancel", cancel_contract)],
    )
    application.add_handler(contract_conv)
    
    return application

def main():
    app = create_creator_app()
    if app:
        print("Creator Bot starting...")
        app.run_polling()

if __name__ == "__main__":
    main()
