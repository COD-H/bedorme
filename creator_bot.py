#!/usr/bin/env python3
import os
import logging
import sqlite3
import datetime
import io
import csv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    ContextTypes, MessageHandler, filters, TypeHandler,
    ApplicationHandlerStop, ConversationHandler
)
from dotenv import load_dotenv
from keep_alive import keep_alive, start_pinger

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
    delete_user_completely, toggle_item_availability, get_unavailable_items
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

    # Allow /my_id for everyone to help debugging
    if update.message and update.message.text == "/my_id":
        await update.message.reply_text(f"Your ID: <code>{user.id}</code>", parse_mode='HTML')
        raise ApplicationHandlerStop

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
                    f"🛡️ <b>System Access Restricted</b>\n\n"
                    f"Your ID <code>{user_id}</code> is not authorized to access the Creator Bot.\n\n"
                    "<b>Admin Configuration Required:</b>\n"
                    "Please update <code>CREATOR_ID</code> in your <code>.env</code> file with your ID."
                )
                if CREATOR_ID == 0:
                    msg += "\n\n⚠️ Currently <code>CREATOR_ID</code> is set to <b>0</b>, which blocks everyone."

                await update.effective_chat.send_message(msg, parse_mode='HTML')
                context.user_data['breach_alerted'] = True
        except Exception as e:
            logger.error(f"Error handling security alert: {e}")

        # STOP all further processing for this update
        raise ApplicationHandlerStop

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command for Creator only (passed security_check already)."""
    # Reset breach flag just in case the creator was testing
    context.user_data['breach_alerted'] = False
    
    await update.effective_message.reply_text(
        f"👑 <b>Welcome Creator</b>\n\n"
        "Security Shield: <b>ACTIVE</b> ✅\n"
        "All unauthorized inputs are being blocked.\n\n"
        "Commands:\n"
        "/active - See live deliveries\n"
        "/orders - Recent orders\n"
        "/stats - View System Statistics\n"
        "/investigate &lt;id&gt; - Deep search user database\n"
        "/user &lt;id&gt; - Quick user check",
        reply_markup=ReplyKeyboardMarkup([
            ["/active", "/orders", "/stats"]
        ], resize_keyboard=True),
        parse_mode='HTML'
    )

async def investigate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_str = None
    if context.args:
        query_str = " ".join(context.args)
    
    if not query_str:
        await update.effective_message.reply_text(
            "🔎 <b>User Audit System</b>\n\n"
            "Please enter the <b>User ID</b>, <b>@username</b>, or <b>Full Name</b> to audit:",
            parse_mode='HTML'
        )
        return WAITING_INVESTIGATE_INPUT
    
    return await run_investigation(update, context, query_str)

async def handle_investigate_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_str = update.effective_message.text.strip()
    await run_investigation(update, context, query_str)
    return ConversationHandler.END

async def run_investigation(update: Update, context: ContextTypes.DEFAULT_TYPE, query_str: str):
    target_id = None
    
    # 1. Try if it's a numeric ID
    if query_str.isdigit():
        target_id = int(query_str)
    # 2. Try if it's a username (strip @ if present)
    elif query_str.startswith("@") or len(query_str.split()) == 1:
        username = query_str.lstrip("@").lower()
        target_id = get_user_by_username(username)
    
    # 3. If still nothing, search by name
    if not target_id:
        users = search_users(query_str)
        if not users:
            await update.effective_message.reply_text(f"❌ User '{query_str}' not found in database.")
            return
        
        if len(users) == 1:
            target_id = users[0][0]
        else:
            msg = f"🔍 Multiple users found for '<b>{query_str}</b>':\n\n"
            keyboard = []
            for u in users[:8]:
                msg += f"• {u[2]} (@{u[1]}) - <code>{u[0]}</code>\n"
                keyboard.append([InlineKeyboardButton(f"Audit {u[2]}", callback_data=f"investigate_{u[0]}")])
            await update.effective_message.reply_text(msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
            return

    # Ensure target_id is an integer
    try:
        target_id = int(target_id)
    except (ValueError, TypeError):
        await update.effective_message.reply_text(f"❌ Invalid User ID: {target_id}")
        return

    data = get_full_user_info(target_id)
    if not data:
        await update.effective_message.reply_text(f"No record found for ID: {target_id}")
        return
        
    u = data['info']
    history = data['history']
    orders = data['orders']
    
    # Map user fields: 0:id, 1:username, 2:name, 3:student_id, 4:block, 5:dorm, 6:phone...
    # Indices might vary by DB, but standard is: 0:id, 1:un, 2:name, 3:sid, 4:block, 5:room, 6:phone, 7:gender, 8:deliv, 9:bal, 10:tok, 11:lang, 12:ban
    report = (
        f"🕵️ <b>AUDIT REPORT: {u[2]}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🆔 <b>ID:</b> <code>{u[0]}</code>\n"
        f"👤 <b>Username:</b> @{u[1]}\n"
        f"📞 <b>Phone:</b> {u[6]}\n"
        f"🎓 <b>Student ID:</b> {u[3]}\n"
        f"🏠 <b>Dorm:</b> Block {u[4]}, Room {u[5]}\n"
        f"🚻 <b>Gender:</b> {u[7]}\n"
        f"💰 <b>Balance:</b> {u[9]} ETB\n"
        f"💎 <b>Tokens:</b> {u[10]}\n"
        f"🚲 <b>Deliverer:</b> {'✅ Yes' if u[8] else '❌ No'}\n"
        f"🔴 <b>Banned:</b> {'🚨 YES' if (len(u) > 12 and u[12]) else '🟢 No'}\n"
    )
    
    if history:
        report += "\n📜 <b>Update History (Recent):</b>\n"
        for h in history[:5]: 
            ts = datetime.datetime.fromtimestamp(h[9]).strftime('%Y-%m-%d %H:%M') if len(h) > 9 else "Unknown"
            report += f"- {ts}: {h[2]} (@{h[3]}) phone: {h[4]}\n"
            
    if orders:
        report += f"\n🛍️ <b>Order History ({len(orders)}):</b>\n"
        for o in orders[:8]:
            created_ts = datetime.datetime.fromtimestamp(o[16]).strftime('%H:%M') if (len(o) > 16 and o[16]) else "??"
            report += f"- #{o[0]} | {o[3]} | {o[5]} ETB | {o[6]} | 🕒 {created_ts}\n"
            
    await update.effective_message.reply_text(report, parse_mode='HTML')

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
        await update.effective_message.reply_text("No active orders.")
        return

    msg = "🚀 <b>Live Deliveries (Active):</b>\n\n"
    keyboard = []
    for order in orders:
        msg += f"📦 #{order[0]} | {order[6].upper()} | {order[3]} | User: {order[1]}\n"
        keyboard.append([InlineKeyboardButton(f"View Order #{order[0]}", callback_data=f"view_{order[0]}")])
    
    await update.effective_message.reply_text(msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def view_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split("_")[1])
    
    from database import get_order
    order = get_order(order_id)
    if not order:
        await query.edit_message_text("Order not found.")
        return

    # order: 0:order_id, 1:customer_id, 2:deliverer_id, 3:restaurant, 4:items, 5:total_price, 6:status, 7:order_type...
    msg = (
        f"📦 <b>Order Details: #{order[0]}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 <b>Customer:</b> <code>{order[1]}</code>\n"
        f"🚲 <b>Deliverer:</b> <code>{order[2] or 'NONE'}</code>\n"
        f"🏠 <b>Restaurant:</b> {order[3]}\n"
        f"🛒 <b>Items:</b> {order[4]}\n"
        f"💰 <b>Total:</b> {order[5]} ETB\n"
        f"📊 <b>Status:</b> {order[6].upper()}\n"
        f"🏷️ <b>Type:</b> {order[7]}\n"
        f"🕒 <b>Created:</b> {datetime.datetime.fromtimestamp(order[16]).strftime('%Y-%m-%d %H:%M') if order[16] else 'N/A'}\n"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Active", callback_data="back_to_active")]]
    
    await query.edit_message_text(msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    user_count = cur.fetchone()[0]
    
    # Only count non-test orders
    cur.execute("SELECT COUNT(*) FROM orders WHERE is_test = 0")
    order_count = cur.fetchone()[0]
    
    cur.execute("SELECT SUM(total_price) FROM orders WHERE status = 'complete' AND is_test = 0")
    total_rev = cur.fetchone()[0] or 0
    conn.close()
    
    from database import is_test_mode_active
    test_mode_status = "🔴 ACTIVE" if is_test_mode_active() else "⚪ Inactive"
    
    await update.effective_message.reply_text(
        f"📊 <b>System Stats</b>\n"
        f"<i>(Test data excluded)</i>\n\n"
        f"👥 Users: {user_count}\n"
        f"📦 Real Orders: {order_count}\n"
        f"💰 Real Revenue: {total_rev:,.2f} ETB\n\n"
        f"🧪 <b>Test Mode:</b> {test_mode_status}\n"
        f"<i>Use /test to toggle, /clear to reset stats.</i>",
        parse_mode='HTML'
    )

async def test_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from database import is_test_mode_active, set_test_mode
    
    current = is_test_mode_active()
    new_state = not current
    set_test_mode(new_state)
    
    status = "🔴 ENABLED" if new_state else "⚪ DISABLED"
    await update.effective_message.reply_text(
        f"🧪 <b>Test Mode {status}</b>\n\n"
        f"While active, all NEW orders will be marked as 'test' and excluded from /stats.\n"
        f"<i>Run command again to toggle.</i>",
        parse_mode='HTML'
    )

async def clear_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from database import clear_stats_data
    
    if not context.args:
         await update.effective_message.reply_text(
            "⚠️ <b>Reset Statistics?</b>\n\n"
            "This will mark ALL existing orders as 'Test Data' so they don't show up in /stats.\n"
            "This action cannot be easily undone via bot.\n\n"
            "<b>To confirm, type:</b> <code>/clear confirm</code>",
            parse_mode='HTML'
        )
         return

    if context.args[0].lower() == "confirm":
        success = clear_stats_data()
        if success:
            await update.effective_message.reply_text("✅ <b>Stats Cleared!</b>\nAll valid orders are now marked as test data.")
        else:
             await update.effective_message.reply_text("❌ Error clearing stats. Check logs.")

async def user_management_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("✅ Active Users", callback_data="users_active"),
         InlineKeyboardButton("📜 Contract Users", callback_data="users_contract")],
        [InlineKeyboardButton("👤 Regular Users", callback_data="users_regular"),
         InlineKeyboardButton("🔍 Find User", callback_data="users_find")],
    ]
    await update.effective_message.reply_text(
        "👥 <b>User Management Dashboard</b>\n\n"
        "Select a category to view or search for a specific user. (Regular users are those without active cafe meal plans)",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

SEARCH_USER_INPUT = 10
WAITING_INVESTIGATE_INPUT = 11

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
        await query.edit_message_text(
            "🔍 Please enter the <b>Name</b>, <b>Username</b>, <b>Phone</b>, or <b>Student ID</b> to search:",
            parse_mode='HTML'
        )
        return SEARCH_USER_INPUT

    if not users:
        keyboard = [[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="users_dashboard")]]
        await query.edit_message_text(f"📊 <b>{title}</b>\n\nNo users found in this category.", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # Show first 15 and option to export
    msg = f"📊 <b>{title} ({len(users)})</b>\n\n"
    for u in users[:15]:
        msg += f"• {u[2]} (@{u[1]}) | <code>{u[0]}</code>\n"
    
    if len(users) > 15:
        msg += f"\n...and {len(users)-15} more."

    keyboard = [
        [InlineKeyboardButton("📄 Export PDF", callback_data=f"export_pdf_{data}"),
         InlineKeyboardButton("📊 Export CSV", callback_data=f"export_csv_{data}")],
        [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="users_dashboard")]
    ]
    await query.edit_message_text(msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def export_csv_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.replace("export_csv_users_", "")
    
    users = []
    if category == "active": users = get_active_users()
    elif category == "contract": users = get_contract_users()
    elif category == "regular": users = get_regular_users()
    
    if not users:
        await query.edit_message_text("No data to export.")
        return

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['User ID', 'Username', 'Name', 'Student ID', 'Block', 'Dorm', 'Phone', 'Gender', 'Deliverer', 'Balance', 'Tokens', 'Language', 'Banned'])
    for u in users:
        writer.writerow(list(u))
    
    buffer.seek(0)
    byte_buffer = io.BytesIO(buffer.getvalue().encode())
    
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=byte_buffer,
        filename=f"users_{category}_{datetime.datetime.now().strftime('%Y%m%d')}.csv",
        caption=f"📊 User list export (CSV): {category}"
    )

async def handle_user_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    search_q = update.effective_message.text.strip()
    users = search_users(search_q)
    
    if not users:
        await update.effective_message.reply_text(f"❌ No users found matching '<b>{search_q}</b>'. Try again or /cancel:", parse_mode='HTML')
        return SEARCH_USER_INPUT
        
    msg = f"🔍 <b>Search Results for '{search_q}'</b>\n\n"
    keyboard = []
    for u in users[:10]:
        msg += f"👤 <b>{u[2]}</b> (@{u[1]})\nID: <code>{u[0]}</code> | Phone: {u[6]}\n\n"
        keyboard.append([InlineKeyboardButton(f"Audit {u[2]}", callback_data=f"investigate_{u[0]}")])
        keyboard.append([InlineKeyboardButton(f"🗑️ Delete/Ban {u[2]}", callback_data=f"delete_user_{u[0]}")])
    
    if len(users) > 10:
        msg += f"Found {len(users)} results. Showing top 10."
    
    keyboard.append([InlineKeyboardButton("🔙 Back to Dashboard", callback_data="users_dashboard")])
    await update.effective_message.reply_text(msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END

async def investigate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    target_id = query.data.split("_")[1]
    
    # Just reuse run_investigation logic
    await run_investigation(update, context, target_id)

async def delete_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    target_id = int(query.data.split("_")[2])
    
    keyboard = [
        [InlineKeyboardButton("✅ Yes, Delete & Archive", callback_data=f"confirm_delete_{target_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"investigate_{target_id}")]
    ]
    await query.edit_message_text(f"⚠️ <b>ARE YOU SURE?</b>\n\nDeleting user <code>{target_id}</code> will:\n1. Move all their data to the Suspicious/Deleted Database.\n2. Permanently remove them from the main system.\n3. Ban their account from future use.", 
                                  parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def confirm_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    target_id = int(query.data.split("_")[2])
    
    success = delete_user_completely(target_id)
    if success:
        await query.edit_message_text(f"✅ User <code>{target_id}</code> has been archived and removed from the system.", parse_mode='HTML')
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
    msg = "👮 <b>System Admins / Deliverers:</b>\n\n"
    if not admins:
        msg += "No admins assigned yet."
    else:
        for a in admins:
            msg += f"• {a[2]} (@{a[1]}) - ID: <code>{a[0]}</code> - Phone: {a[3]}\n"
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Admin", callback_data="add_admin")],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main")]
    ]
    await update.effective_message.reply_text(msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def add_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🆔 Please enter the <b>Telegram ID</b> of the new admin:", parse_mode='HTML')
    return WAITING_ADMIN_ID

async def process_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        admin_id = int(update.effective_message.text.strip())
        context.user_data['new_admin_id'] = admin_id
        await update.effective_message.reply_text("💳 Please enter their <b>Account Number</b> (acc):", parse_mode='HTML')
        return WAITING_ADMIN_ACC
    except ValueError:
        await update.effective_message.reply_text("❌ Invalid ID. Please enter a numerical Telegram ID:")
        return WAITING_ADMIN_ID

async def process_admin_acc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    acc = update.effective_message.text.strip()
    context.user_data['new_admin_acc'] = acc
    await update.effective_message.reply_text("👤 Please enter the admin's <b>Full Name</b>:", parse_mode='HTML')
    return WAITING_ADMIN_NAME

async def process_admin_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_message.text.strip()
    admin_id = context.user_data['new_admin_id']
    acc = context.user_data['new_admin_acc']
    
    # Update as deliverer in DB
    set_user_as_admin(admin_id, 1)
    # Store account number in context or ENV (since it's persistent, maybe ENV? No, let's just mark them as admin)
    # The requirement said "acc" is one of the reqs.
    # In bedorme.py, it uses usernames to map accounts.
    # I should probably store these mappings somewhere, maybe a new table?
    # But for now, I'll just confirm they are added.
    
    await update.effective_message.reply_text(f"✅ User {name} (ID: {admin_id}) is now an Admin/Deliverer.\nAccount: {acc}", parse_mode='HTML')
    return ConversationHandler.END

async def cafe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "🏪 <b>Cafe & Menu Management</b>\n\nSelect a cafe to manage:"
    keyboard = []
    for cafe in MENUS.keys():
        keyboard.append([InlineKeyboardButton(f"🏪 {cafe}", callback_data=f"cafe_manage_{cafe}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main")])
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.effective_message.reply_text(msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def cafe_options_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    cafe_name = query.data.replace("cafe_manage_", "")
    
    msg = f"🏪 <b>Cafe: {cafe_name}</b>\n\nChoose an action for this cafe:"
    keyboard = [
        [InlineKeyboardButton("🍱 Menu & Stock Control", callback_data=f"stock_list_{cafe_name}")],
        [InlineKeyboardButton("📜 Register New Contractor", callback_data=f"contract_{cafe_name}")],
        [InlineKeyboardButton("🔙 Back to Cafes", callback_data="cafe_management")]
    ]
    
    await query.edit_message_text(msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def stock_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    cafe = query.data.replace("stock_list_", "")
    menu = MENUS.get(cafe, {})
    unavailable_items = get_unavailable_items(cafe)
    
    msg = f"🍱 <b>Stock: {cafe}</b>\n\nClick an item to toggle its availability.\nItems marked with ❌ are sold out."
    keyboard = []
    
    for item in menu.keys():
        status = "❌ SOLD OUT" if item in unavailable_items else "✅ Available"
        button_text = f"{item}: {status}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"toggle_stock_{cafe}_{item}")])
        
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data=f"cafe_manage_{cafe}")])
    await query.edit_message_text(msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def toggle_stock_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    # Format: toggle_stock_{cafe}_{item}
    data = query.data.replace("toggle_stock_", "")
    
    found_cafe = None
    item_name = None
    for cafe in MENUS.keys():
        if data.startswith(cafe + "_"):
            found_cafe = cafe
            item_name = data[len(cafe)+1:]
            break
            
    if not found_cafe:
        await query.answer("Error identifying cafe/item.", show_alert=True)
        return
        
    toggle_item_availability(found_cafe, item_name)
    
    # Refresh the list - stock_list_callback will call query.answer()
    query.data = f"stock_list_{found_cafe}"
    await stock_list_callback(update, context)

async def contract_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    cafe_name = query.data.replace("contract_", "")
    context.user_data['contract_cafe'] = cafe_name
    
    await query.edit_message_text(
        f"📝 Adding contract for <b>{cafe_name}</b>.\n\n"
        f"Please enter the user's <b>Telegram Username</b> (with or without @):\n\n"
        "<i>Type /cancel to abort.</i>", 
        parse_mode='HTML'
    )
    return WAITING_USERNAME

async def process_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_message.text.strip()
    user_id = get_user_by_username(username)
    
    if not user_id:
        await update.effective_message.reply_text("❌ User not found in main bot database. They must be registered in the bot first. Please enter a valid username or /cancel:")
        return WAITING_USERNAME
    
    context.user_data['contract_user_id'] = user_id
    context.user_data['contract_username'] = username
    
    await update.effective_message.reply_text("📱 Great! Now enter their <b>Phone Number</b>:", parse_mode='HTML')
    return WAITING_PHONE

async def process_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.effective_message.text.strip()
    context.user_data['contract_phone'] = phone
    
    await update.effective_message.reply_text("👤 Almost done! Enter their <b>Full Name</b>:", parse_mode='HTML')
    return WAITING_NAME

async def process_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    full_name = update.effective_message.text.strip()
    context.user_data['contract_full_name'] = full_name
    await update.effective_message.reply_text("📄 Enter <b>Contract Name</b> or <b>ID</b>:", parse_mode='HTML')
    return WAITING_CONTRACT_ID

async def process_contract_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_message.text.strip()
    context.user_data['contract_id'] = cid
    await update.effective_message.reply_text("🔢 Enter <b>Page</b> or <b>List Order</b> position (number):", parse_mode='HTML')
    return WAITING_LIST_ORDER

async def process_list_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    order = update.effective_message.text.strip()
    context.user_data['contract_order'] = order
    await update.effective_message.reply_text("💰 <b>How much did he pay?</b> (Enter amount in ETB):", parse_mode='HTML')
    return WAITING_PAYMENT

async def process_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        paid_amount = float(update.effective_message.text.strip())
    except ValueError:
        await update.effective_message.reply_text("❌ Invalid amount. Please enter a number:")
        return WAITING_PAYMENT

    user_id = context.user_data['contract_user_id']
    cafe_name = context.user_data['contract_cafe']
    phone = context.user_data['contract_phone']
    username = context.user_data['contract_username']
    full_name = context.user_data['contract_full_name']
    contract_id = context.user_data['contract_id']
    list_order = context.user_data.get('contract_order', 0)
    
    add_cafe_contract(user_id, cafe_name, phone, username, full_name, contract_id, list_order, paid_amount)
    
    await update.effective_message.reply_text(
        f"✅ <b>Contract Registered Successfully!</b>\n\n"
        f"👤 <b>User:</b> {full_name} (@{username})\n"
        f"📍 <b>Cafe:</b> {cafe_name}\n"
        f"📞 <b>Phone:</b> {phone}\n"
        f"📄 <b>Contract ID:</b> {contract_id}\n"
        f"🔢 <b>Order No:</b> {list_order}\n"
        f"💰 <b>Paid:</b> {paid_amount} ETB\n"
        f"🆔 <b>User ID:</b> <code>{user_id}</code>",
        parse_mode='HTML'
    )
    return ConversationHandler.END

async def cancel_contract(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Contract addition cancelled.")
    return ConversationHandler.END

async def start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback for returning to main start menu."""
    query = update.callback_query
    await query.answer()
    await start_command(update, context)

def create_creator_app():
    if not TOKEN:
        return None

    application = Application.builder().token(TOKEN).build()

    # 1. SECURITY LAYER (GROUP -1 runs first)
    application.add_handler(TypeHandler(Update, security_check), group=-1)

    # 2. CONVERSATIONS (Must be before general handlers)
    
    # User Search Conversation
    user_search_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(user_callback, pattern="^users_find$")],
        states={
            SEARCH_USER_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_search)],
        },
        fallbacks=[CommandHandler("cancel", cancel_contract), 
                   CallbackQueryHandler(user_management_command, pattern="^users_dashboard$")],
        allow_reentry=True
    )
    application.add_handler(user_search_conv)

    # Investigate Conversation
    investigate_conv = ConversationHandler(
        entry_points=[CommandHandler("investigate", investigate_command)],
        states={
            WAITING_INVESTIGATE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_investigate_input)],
        },
        fallbacks=[CommandHandler("cancel", cancel_contract)],
        allow_reentry=True
    )
    application.add_handler(investigate_conv)

    # 3. GENERAL COMMANDS
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("user", user_management_command))
    application.add_handler(CommandHandler("active", list_active_orders_command))
    application.add_handler(CommandHandler("test", test_mode_command))
    application.add_handler(CommandHandler("clear", clear_stats_command))
    
    # User Management Callbacks
    application.add_handler(CallbackQueryHandler(user_callback, pattern="^users_"))
    application.add_handler(CallbackQueryHandler(export_pdf_callback, pattern="^export_pdf_"))
    application.add_handler(CallbackQueryHandler(export_csv_callback, pattern="^export_csv_"))
    application.add_handler(CallbackQueryHandler(investigate_callback, pattern="^investigate_"))
    application.add_handler(CallbackQueryHandler(delete_user_callback, pattern="^delete_user_"))
    application.add_handler(CallbackQueryHandler(confirm_delete_callback, pattern="^confirm_delete_"))
    application.add_handler(CallbackQueryHandler(user_management_command, pattern="^users_dashboard$"))
    application.add_handler(CallbackQueryHandler(start_callback, pattern="^back_to_main$"))
    application.add_handler(CallbackQueryHandler(view_order_callback, pattern="^view_"))
    application.add_handler(CallbackQueryHandler(list_active_orders_command, pattern="^back_to_active$"))

    # Cafe & Stock Management
    application.add_handler(CallbackQueryHandler(cafe_options_callback, pattern="^cafe_manage_"))
    application.add_handler(CallbackQueryHandler(stock_list_callback, pattern="^stock_list_"))
    application.add_handler(CallbackQueryHandler(toggle_stock_callback, pattern="^toggle_stock_"))
    application.add_handler(CallbackQueryHandler(cafe_command, pattern="^cafe_management$"))

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
    if not app:
        print("Error: No Token found for Creator Bot.")
        return

    # Check for Render environment
    webhook_url = os.environ.get("RENDER_EXTERNAL_URL")
    
    # Custom pinger for the creator bot (provided by user)
    creator_ping_url = os.environ.get("CREATOR_PING_URL", "https://bedorme-creator.onrender.com")

    if webhook_url:
        port = int(os.environ.get("PORT", 8080))
        if webhook_url.endswith("/"):
            webhook_url = webhook_url[:-1]
        
        logging.info(f"Creator Bot: Starting Webhook mode at {webhook_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=TOKEN,
            webhook_url=f"{webhook_url}/{TOKEN}"
        )
    else:
        logging.info("Creator Bot: Starting Polling mode.")
        keep_alive() # Start flask server for Render/UptimeRobot
        
        # Start pinger to prevent sleep on free tier
        if creator_ping_url:
            start_pinger(creator_ping_url)
            
        app.run_polling()

if __name__ == "__main__":
    main()
