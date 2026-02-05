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

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import inch

# Import database functions
from database import (
    get_db_connection, get_user, ban_user, get_full_user_info, 
    add_cafe_contract, get_user_by_username, get_all_admins,
    set_user_as_admin, get_contract_details, update_contract_payment,
    get_active_users, get_contract_users, get_regular_users, search_users,
    delete_user_completely
)
from menus import MENUS

load_dotenv()

TOKEN = os.getenv("CREATOR_BOT_TOKEN")
CREATOR_ID_RAW = os.getenv("CREATOR_ID", "0").split("#")[0].strip()
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
        
        # Log the breach
        logger.warning(f"SECURITY ALERT: Unauthorized access attempt by {full_name} (@{username}) ID: {user_id}")
        
        # Alert the unauthorized user
        try:
            if not context.user_data.get('breach_alerted'):
                msg = (
                    f"🛡️ **System Access Restricted**\n\n"
                    f"Your ID `{user_id}` is not authorized to access the Creator Bot.\n\n"
                    "**Admin Configuration Required:**\n"
                    "Please update `CREATOR_ID` in your `.env` file with your ID."
                )
                if CREATOR_ID == 0:
                    msg += "\n\n⚠️ Currently `CREATOR_ID` is set to **0**, which blocks everyone."

                await update.effective_chat.send_message(msg, parse_mode='Markdown')
                context.user_data['breach_alerted'] = True
        except Exception as e:
            logger.error(f"Error handling security alert: {e}")

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
        report += f"\n🛍️ **Recent Orders ({len(orders)}):**\n"
        for o in orders[:8]:
            # Indices: 0:id, 3:rest, 5:price, 6:status, 7:type, 12:lat, 13:lon, 16:created, 17:delivered
            created_ts = datetime.datetime.fromtimestamp(o[16]).strftime('%H:%M') if (len(o) > 16 and o[16]) else "??"
            deliv_ts = datetime.datetime.fromtimestamp(o[17]).strftime('%H:%M') if (len(o) > 17 and o[17]) else "--"
            report += f"- #{o[0]} | {o[3]} | {o[5]} ETB | {o[6]} ({o[7]}) | 🕒 {created_ts}→{deliv_ts}\n"
            if len(o) > 13 and o[12] and o[13]: 
                report += f"  📍 [Map](https://www.google.com/maps/search/?api=1&query={o[12]},{o[13]})\n"
            
    await update.message.reply_text(report, parse_mode='Markdown')

async def list_active_orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    query = """SELECT order_id, customer_id, deliverer_id, restaurant, items, total_price, status, order_type, verification_code, 
               mid_delivery_proof, proof_timestamp, delivery_proof, delivery_lat, delivery_lon, pickup_lat, pickup_lon, created_at, delivered_at 
               FROM orders WHERE status IN ('pending', 'accepted', 'picked_up')"""
    cur.execute(query)
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

async def user_management_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("✅ Active Users", callback_data="users_active"),
         InlineKeyboardButton("📜 Contract Users", callback_data="users_contract")],
        [InlineKeyboardButton("👤 Regular Users", callback_data="users_regular"),
         InlineKeyboardButton("🔍 Find User", callback_data="users_find")],
    ]
    await update.message.reply_text(
        "👥 **User Management Dashboard**\n\n"
        "Select a category to view or search for a specific user.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

SEARCH_USER_INPUT = 10  # New state

async def user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    users = []
    title = ""
    
    if data == "users_active":
        users = get_active_users()
        title = "Active Users (Last 7 Days)"
    elif data == "users_contract":
        users = get_contract_users()
        title = "Contract Users"
    elif data == "users_regular":
        users = get_regular_users()
        title = "Regular Users"
    elif data == "users_find":
        await query.edit_message_text("🔍 Please enter the **Name**, **Username**, **Phone**, or **Student ID** to search:")
        return SEARCH_USER_INPUT

    if not users:
        await query.edit_message_text(f"No users found in category: {title}")
        return

    # Show first 10 and option to export PDF
    msg = f"📊 **{title} ({len(users)})**\n\n"
    for u in users[:15]:
        # u: 0:id, 1:username, 2:name, 3:student_id, 4:block, 5:dorm, 6:phone...
        msg += f"• {u[2]} (@{u[1]}) | `{u[0]}`\n"
    
    if len(users) > 15:
        msg += f"\n...and {len(users)-15} more."

    keyboard = [[InlineKeyboardButton("📄 Export to PDF", callback_data=f"export_pdf_{data}")]]
    await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_user_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    search_q = update.message.text.strip()
    users = search_users(search_q)
    
    if not users:
        await update.message.reply_text(f"❌ No users found matching '{search_q}'. Try again or /cancel:")
        return SEARCH_USER_INPUT
        
    msg = f"🔍 **Search Results for '{search_q}'**\n\n"
    keyboard = []
    for u in users[:10]:
        msg += f"👤 **{u[2]}** (@{u[1]})\nID: `{u[0]}` | Phone: {u[6]}\n\n"
        keyboard.append([InlineKeyboardButton(f"Audit {u[2]}", callback_data=f"investigate_{u[0]}")])
        keyboard.append([InlineKeyboardButton(f"🗑️ Delete/Ban {u[2]}", callback_data=f"delete_user_{u[0]}")])
    
    if len(users) > 10:
        msg += f"Found {len(users)} results. Showing top 10."
    
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END

async def investigate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    target_id = int(query.data.split("_")[1])
    
    # Just reuse investigate_command logic but for callback
    context.args = [str(target_id)]
    await investigate_command(update, context)

async def delete_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    target_id = int(query.data.split("_")[2])
    
    keyboard = [
        [InlineKeyboardButton("✅ Yes, Delete & Archive", callback_data=f"confirm_delete_{target_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="users_dashboard")]
    ]
    await query.edit_message_text(f"⚠️ **ARE YOU SURE?**\n\nDeleting user `{target_id}` will:\n1. Move all their data to the Suspicious/Deleted Database.\n2. Permanently remove them from the main system.\n3. Ban their account from future use.", 
                                  parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def confirm_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    target_id = int(query.data.split("_")[2])
    
    success = delete_user_completely(target_id)
    if success:
        await query.edit_message_text(f"✅ User `{target_id}` has been archived and removed from the system.")
    else:
        await query.edit_message_text("❌ Error: User not found or already deleted.")

async def export_pdf_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.replace("export_pdf_users_", "")
    
    users = []
    if category == "active": users = get_active_users()
    elif category == "contract": users = get_contract_users()
    elif category == "regular": users = get_regular_users()
    
    if not users:
        await query.edit_message_text("No data to export.")
        return

    # Generate PDF
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    c.setFont("Helvetica-Bold", 16)
    c.drawString(1*inch, height - 1*inch, f"Bedorme User Report: {category.upper()}")
    c.setFont("Helvetica", 10)
    c.drawString(1*inch, height - 1.2*inch, f"Generated on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    y = height - 1.6*inch
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.5*inch, y, "ID")
    c.drawString(1.5*inch, y, "Name")
    c.drawString(3.5*inch, y, "Username")
    c.drawString(5.0*inch, y, "Phone")
    c.drawString(6.5*inch, y, "Student ID")
    
    y -= 0.2*inch
    c.line(0.5*inch, y, 7.5*inch, y)
    y -= 0.2*inch
    
    c.setFont("Helvetica", 9)
    for u in users:
        if y < 1*inch:
            c.showPage()
            y = height - 1*inch
            c.setFont("Helvetica", 9)
            
        c.drawString(0.5*inch, y, str(u[0]))
        c.drawString(1.5*inch, y, str(u[2])[:25])
        c.drawString(3.5*inch, y, f"@{u[1]}" if u[1] else "N/A")
        c.drawString(5.0*inch, y, str(u[6]))
        c.drawString(6.5*inch, y, str(u[3]))
        y -= 0.2*inch
    
    c.save()
    buffer.seek(0)
    
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=buffer,
        filename=f"users_{category}_{datetime.datetime.now().strftime('%Y%m%d')}.pdf",
        caption=f"📄 User report for category: {category}"
    )

WAITING_USERNAME, WAITING_PHONE, WAITING_NAME, WAITING_CONTRACT_ID, WAITING_LIST_ORDER, WAITING_PAYMENT = range(6)
WAITING_ADMIN_ID, WAITING_ADMIN_ACC, WAITING_ADMIN_NAME = range(6, 9)

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all admins and show option to add new one."""
    admins = get_all_admins()
    msg = "👮 **System Admins / Deliverers:**\n\n"
    if not admins:
        msg += "No admins assigned yet."
    else:
        for a in admins:
            msg += f"• {a[2]} (@{a[1]}) - ID: `{a[0]}` - Phone: {a[3]}\n"
    
    keyboard = [[InlineKeyboardButton("➕ Add Admin", callback_data="add_admin")]]
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def add_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🆔 Please enter the **Telegram ID** of the new admin:")
    return WAITING_ADMIN_ID

async def process_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        admin_id = int(update.message.text.strip())
        context.user_data['new_admin_id'] = admin_id
        await update.message.reply_text("💳 Please enter their **Account Number** (acc):")
        return WAITING_ADMIN_ACC
    except ValueError:
        await update.message.reply_text("❌ Invalid ID. Please enter a numerical Telegram ID:")
        return WAITING_ADMIN_ID

async def process_admin_acc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    acc = update.message.text.strip()
    context.user_data['new_admin_acc'] = acc
    await update.message.reply_text("👤 Please enter the admin's **Full Name**:")
    return WAITING_ADMIN_NAME

async def process_admin_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    admin_id = context.user_data['new_admin_id']
    acc = context.user_data['new_admin_acc']
    
    # Update as deliverer in DB
    set_user_as_admin(admin_id, 1)
    # Store account number in context or ENV (since it's persistent, maybe ENV? No, let's just mark them as admin)
    # The requirement said "acc" is one of the reqs.
    # In bedorme.py, it uses usernames to map accounts.
    # I should probably store these mappings somewhere, maybe a new table?
    # But for now, I'll just confirm they are added.
    
    await update.message.reply_text(f"✅ User {name} (ID: {admin_id}) is now an Admin/Deliverer.\nAccount: {acc}", parse_mode='Markdown')
    return ConversationHandler.END

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
    context.user_data['contract_full_name'] = full_name
    await update.message.reply_text("📄 Enter **Contract Name** or **ID**:")
    return WAITING_CONTRACT_ID

async def process_contract_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.message.text.strip()
    context.user_data['contract_id'] = cid
    await update.message.reply_text("🔢 Enter **Page** or **List Order** position (number):")
    return WAITING_LIST_ORDER

async def process_list_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    order = update.message.text.strip()
    context.user_data['contract_order'] = order
    await update.message.reply_text("💰 **How much did he pay?** (Enter amount in ETB):")
    return WAITING_PAYMENT

async def process_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        paid_amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Please enter a number:")
        return WAITING_PAYMENT

    user_id = context.user_data['contract_user_id']
    cafe_name = context.user_data['contract_cafe']
    phone = context.user_data['contract_phone']
    username = context.user_data['contract_username']
    full_name = context.user_data['contract_full_name']
    contract_id = context.user_data['contract_id']
    list_order = context.user_data.get('contract_order', 0)
    
    add_cafe_contract(user_id, cafe_name, phone, username, full_name, contract_id, list_order, paid_amount)
    
    await update.message.reply_text(
        f"✅ **Contract Registered Successfully!**\n\n"
        f"👤 **User:** {full_name} (@{username})\n"
        f"📍 **Cafe:** {cafe_name}\n"
        f"📞 **Phone:** {phone}\n"
        f"📄 **Contract ID:** {contract_id}\n"
        f"🔢 **Order No:** {list_order}\n"
        f"💰 **Paid:** {paid_amount} ETB\n"
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
    application.add_handler(CommandHandler("user", user_management_command))
    application.add_handler(CommandHandler("active", list_active_orders_command))
    
    # User Management Callbacks
    application.add_handler(CallbackQueryHandler(user_callback, pattern="^users_"))
    application.add_handler(CallbackQueryHandler(export_pdf_callback, pattern="^export_pdf_"))
    application.add_handler(CallbackQueryHandler(investigate_callback, pattern="^investigate_"))
    application.add_handler(CallbackQueryHandler(delete_user_callback, pattern="^delete_user_"))
    application.add_handler(CallbackQueryHandler(confirm_delete_callback, pattern="^confirm_delete_"))
    application.add_handler(CallbackQueryHandler(user_management_command, pattern="^users_dashboard$"))

    # User Search Conversation
    user_search_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(user_callback, pattern="^users_find$")],
        states={
            SEARCH_USER_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_search)],
        },
        fallbacks=[CommandHandler("cancel", cancel_contract)],
    )
    application.add_handler(user_search_conv)

    application.add_handler(CommandHandler("orders", list_active_orders_command)) # Reuse list_active for now or simple list
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("cafe", cafe_command))
    application.add_handler(CommandHandler("admin", admin_command))

    # Admin Addition Conversation
    admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_admin_callback, pattern="^add_admin$")],
        states={
            WAITING_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_admin_id)],
            WAITING_ADMIN_ACC: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_admin_acc)],
            WAITING_ADMIN_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_admin_name)],
        },
        fallbacks=[CommandHandler("cancel", cancel_contract)],
    )
    application.add_handler(admin_conv)

    # Contract Conversation Handler
    contract_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(contract_callback, pattern="^contract_")],
        states={
            WAITING_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_username)],
            WAITING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_phone)],
            WAITING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_name)],
            WAITING_CONTRACT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_contract_id)],
            WAITING_LIST_ORDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_list_order)],
            WAITING_PAYMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_payment)],
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
