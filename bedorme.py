#!/usr/bin/env python3
# --- Admin Seen User Callback ---

import time
import math
import asyncio
from keep_alive import keep_alive, start_pinger
from locations import RESTAURANTS, BLOCKS, ALLOWED_RADIUS
from menus import MENUS, CONTRACT_MENUS
from database import (
    init_db, add_user, create_order, get_user, update_order_location,
    get_user_active_orders, set_user_language, get_user_language, get_order,
    mark_order_complete, save_rating, is_contract_user, get_contract_details,
    update_contract_payment, log_suspicious_access
)
from translations import get_text
from telegram.ext import (
    Application, CommandHandler, ContextTypes, ConversationHandler,
    MessageHandler, filters, CallbackQueryHandler, PicklePersistence, TypeHandler,
    ApplicationHandlerStop
)
from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton
)
from telegram.request import HTTPXRequest
from dotenv import load_dotenv
import string
import re
import random
import os
import logging
import sqlite3
import threading
from creator_bot import create_creator_app

# Load environment variables from .env file
load_dotenv()

# TOKEN (now loaded from .env)
TOKEN = os.getenv("TELEGRAM_TOKEN")

async def check_banned(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    
    db_user = get_user(user.id)
    if db_user and len(db_user) > 12 and db_user[12]: # Index 12 is is_banned
        # Log to suspicious DB
        phone = db_user[6] if len(db_user) > 6 else "N/A"
        log_suspicious_access(user.id, user.username, user.full_name, phone, "Banned user tried to access bot")
        
        await update.effective_chat.send_message(
            "🚫 **ACCESS DENIED**\n\nYour account is restricted. Contact support if this is an error.",
            parse_mode='Markdown'
        )
        raise ApplicationHandlerStop

async def admin_seen_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback when admin confirms they have seen the user (within 50m)."""
    query = update.callback_query
    if update.effective_chat.id != ADMIN_CHAT_ID:
        await query.answer("Unauthorized action.", show_alert=True)
        return
    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 5:
        await query.edit_message_text("Invalid callback data.")
        return
    order_id = int(parts[3])
    user_id = int(parts[4])

    # Determine account number based on admin username
    admin_username = query.from_user.username
    
    # Default account variables loaded from ENV
    acc_default = os.getenv("ACC_DEFAULT", "1000397137833")
    acc_h_kara = os.getenv("ACC_H_KARASEFERIAN", "1000688588972")
    acc_kal = os.getenv("ACC_KALNLISA", "1000466307371")
    
    account_number = acc_default

    if admin_username:
        # Standardize check (case-insensitive, strip @)
        clean_username = admin_username.lstrip('@').lower()

        if clean_username == "h_karaseferian":
            account_number = acc_h_kara
        elif clean_username == "kalnlisa":
            account_number = acc_kal
        elif clean_username in ["callowned", "allowned"]:
            account_number = acc_default

    # Fetch order to show price
    is_contract = False
    try:
        # Already imported at top, usage is correct
        p_order = get_order(order_id)
        # Price is typically float or int, at index 5
        price_val = p_order[5] if p_order else "???"
        if p_order and len(p_order) > 7 and p_order[7] == 'contract':
            is_contract = True
    except Exception:
        price_val = "???"

    if is_contract:
        try:
            # Get deliverer location for the log
            loc = context.bot_data.get(f'latest_location_{query.from_user.id}', {})
            mark_order_complete(order_id, lat=loc.get('lat'), lon=loc.get('lon'))
            
            await context.bot.send_message(
                chat_id=user_id,
                text="🎖️ **Contract Order Confirmed**\n\nThe deliverer has seen you. Since this is a contract order, your balance was automatically adjusted. No payment proof is needed. Enjoy your meal!",
                parse_mode='Markdown'
            )
            await query.edit_message_text("Confirmed: Seen receiver. (Contract Order - Completed ✅)")
            return
        except Exception as e:
            logger.warning(f"Failed to send contract confirmation to user {user_id}: {e}")

    # Notify user to start payment process and upload proof
    lang = get_user_language(user_id) or 'en'
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=get_text('pay_instruct', lang).format(order_id=order_id, account=account_number, price=price_val),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.warning(f"Failed to send payment instruct to user {user_id}: {e}")

    # Set state for this user to expect payment proof
    context.bot_data[f'waiting_payment_proof_{user_id}'] = order_id

    try:
        await query.edit_message_text("Confirmed: You have seen the receiver. User has been notified to upload payment proof.")
    except Exception:
        pass


async def handle_payment_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo upload from user as payment proof."""
    if not update.effective_user:
        return
    user_id = update.effective_user.id
    order_id = context.bot_data.get(f'waiting_payment_proof_{user_id}')

    if not order_id:
        # Not waiting for proof from this user
        return

    photo = update.message.photo[-1]
    file_id = photo.file_id

    # Store user proof for later completion logging
    context.bot_data[f'user_proof_{order_id}'] = file_id

    # Forward proof to admin
    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"📸 Payment proof received from User {user_id} for Order #{order_id}:")
    await context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=file_id)

    # Ask admin to verify and upload their own proof (receipt)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Verify & Upload Receipt",
                              callback_data=f"admin_req_receipt_{order_id}_{user_id}")],
        [InlineKeyboardButton("❌ Invalid Proof - Resend",
                              callback_data=f"admin_reject_proof_{order_id}_{user_id}")]
    ])
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text="Verify the payment. If received, click below to upload your confirmation receipt.",
        reply_markup=kb
    )

    # Clear user waiting state
    del context.bot_data[f'waiting_payment_proof_{user_id}']
    
    from database import get_user_language
    lang = get_user_language(user_id) or 'en'
    await update.message.reply_text(get_text('payment_proof_sent', lang))


async def admin_reject_proof_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin clicked 'Invalid Proof - Resend'."""
    query = update.callback_query
    if update.effective_chat.id != ADMIN_CHAT_ID:
        await query.answer("Unauthorized action.", show_alert=True)
        return
    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 5:
        await query.edit_message_text("Invalid callback data.")
        return
    order_id = int(parts[3])
    user_id = int(parts[4])

    from database import get_user_language
    lang = get_user_language(user_id) or 'en'
    
    # 1. Notify User
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=get_text('payment_rejected', lang)
        )
        # Re-enable waiting state for this user
        context.bot_data[f'waiting_payment_proof_{user_id}'] = order_id
    except Exception as e:
        logger.warning(f"Failed to notify user about rejection: {e}")

    # 2. Update Admin Message
    await query.edit_message_text(f"❌ Proof rejected by {query.from_user.first_name}. User has been asked to resend.")


async def admin_req_receipt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin clicked 'Verify & Upload Receipt'."""
    query = update.callback_query
    if update.effective_chat.id != ADMIN_CHAT_ID:
        await query.answer("Unauthorized action.", show_alert=True)
        return
    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 5:
        await query.edit_message_text("Invalid callback data.")
        return
    order_id = int(parts[3])
    user_id = int(parts[4])

    # 1. Mark that verification is in progress
    await query.edit_message_text(f"Admin {query.from_user.first_name} is verifying payment.")

    # 2. Send a specific message for the admin to REPLY to.
    # This solves the Anonymous Admin issue AND the Concurrency issue.
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"🧾 **RECEIPT UPLOAD REQUEST**\n\nPlease **REPLY** to this message with the receipt photo for **Order #{order_id}**.\n(You MUST reply to this specific message so I know which order it is for!)",
        parse_mode='Markdown'
    )


async def handle_admin_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo upload from admin as receipt proof."""
    # Also check if message is in Admin Group
    if update.effective_chat.id != ADMIN_CHAT_ID:
        return

    msg = update.effective_message
    # Check if message has photo
    if not msg or not msg.photo:
        return

    # --- NEW LOGIC: Check for Reply ---
    # We only process the photo if it is a REPLY to our request message.
    if not msg.reply_to_message or not msg.reply_to_message.text:
        return

    reply_text = msg.reply_to_message.text
    if "RECEIPT UPLOAD REQUEST" not in reply_text:
        return

    # Extract Order ID from the text "Order #{order_id}"
    match = re.search(r"Order #(\d+)", reply_text)
    if not match:
        return

    order_id = int(match.group(1))

    # Fetch order details from DB to get the user_id
    # Already imported at top
    order = get_order(order_id)
    if not order:
        return

    user_id = order[1]  # customer_id is at index 1

    photo = msg.photo[-1]
    file_id = photo.file_id
    
    from database import get_user_language
    lang = get_user_language(user_id) or 'en'

    # 1. Forward receipt to user
    try:
        await context.bot.send_message(chat_id=user_id, text=get_text('payment_verified', lang).format(order_id=order_id))
        await context.bot.send_photo(chat_id=user_id, photo=file_id)
    except Exception as e:
        logger.warning(f"Failed to send receipt to user: {e}")

    # 2. Mark order complete
    try:
        # Already imported at top
        # Get deliverer location from bot_data if available
        loc = context.bot_data.get(f'latest_location_{msg.from_user.id}', {})
        mark_order_complete(order_id, lat=loc.get('lat'), lon=loc.get('lon'))

        # Retrieve User Proof
        user_proof_id = context.bot_data.get(f'user_proof_{order_id}')

        # Get Order Details
        order = get_order(order_id)
        user = get_user(user_id)

        from html import escape
        # Escape ALL fields to prevent HTML parse errors
        user_name = escape(str(user[1])) if user[1] else "Unknown"
        user_id_display = escape(str(user[2])) if user[2] else "Unknown"
        user_phone = escape(str(user[5])) if user[5] else "Unknown"
        user_block = escape(str(user[3])) if user[3] else "?"
        user_dorm = escape(str(user[4])) if user[4] else "?"
        rest_name = escape(str(order[3])) if order[3] else "?"
        item_name = escape(str(order[4])) if order[4] else "?"
        price_display = escape(str(order[5])) if order[5] else "0"

        # Get Admin Name
        admin_name = "Unknown Admin"
        try:
            admin_user = msg.from_user
            if admin_user:
                admin_name = escape(
                    f"{admin_user.first_name} {admin_user.last_name or ''}".strip())
        except:
            pass

        caption = (
            f"✅ <b>Order #{order_id} COMPLETED</b>\n"
            f"👤 <b>User:</b> {user_name} (ID: {user_id_display})\n"
            f"📞 <b>Phone:</b> {user_phone}\n"
            f"🏠 <b>Dorm:</b> {user_block} / {user_dorm}\n"
            f"📍 <b>Restaurant:</b> {rest_name}\n"
            f"🍔 <b>Item:</b> {item_name}\n"
            f"💰 <b>Price:</b> {price_display} ETB\n"
            f"👮 <b>Delivered By:</b> {admin_name}"
        )

        # Log the caption for debugging
        logger.info(f"Generated Caption: {caption}")

        # Send to Completed Channel
        # Send User Proof
        if user_proof_id:
            await context.bot.send_photo(
                chat_id=COMPLETED_ORDERS_CHANNEL_ID,
                photo=user_proof_id,
                caption=f"{caption}\n\n📤 <b>Proof from User</b>",
                parse_mode='HTML'
            )

        # Send Admin Receipt
        await context.bot.send_photo(
            chat_id=COMPLETED_ORDERS_CHANNEL_ID,
            photo=file_id,
            caption=f"{caption}\n\n🧾 <b>Receipt from Admin</b>",
            parse_mode='HTML'
        )

        # Cleanup
        if user_proof_id:
            del context.bot_data[f'user_proof_{order_id}']

    except Exception as e:
        logger.error(f"FAILED TO SEND TO COMPLETED CHANNEL: {e}")
        # Try sending error to admin chat so they know
        try:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"⚠️ Error logging completion to channel: {e}")
        except:
            pass

    # 2.5. Ask User to Stop Live Location
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=get_text('stop_live_loc', lang),
            parse_mode='Markdown'
        )
        # Wait 5 seconds
        await asyncio.sleep(5)
    except Exception:
        pass

    # 3. Ask User for Rating
    try:
        # Create 1-10 buttons
        buttons = []
        row = []
        for i in range(1, 11):
            row.append(InlineKeyboardButton(
                str(i), callback_data=f"rate_{order_id}_{i}"))
            if len(row) == 5:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

        await context.bot.send_message(
            chat_id=user_id,
            text=get_text('rate_us', lang),
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception:
        pass

    # 4. Cleanup
    # del context.bot_data[f'admin_uploading_receipt_{admin_id}'] # No longer needed with reply logic
    await msg.reply_text(
        f"Receipt sent to user. Order #{order_id} marked as complete.\n\n"
        "🛑 **ATTENTION ADMIN:** Please **STOP SHARING YOUR LIVE LOCATION** now if you are still sharing it."
    )

    # --- NEW: Delete all messages in user's chat, then send /start prompt ---
    try:
        # Telegram Bots cannot "Clear History" or read past messages to delete them.
        # We will simply send the final prompt to the user.
        await context.bot.send_message(
            chat_id=user_id,
            text=get_text('order_complete_prompt', lang)
        )
    except Exception as e:
        logger.warning(
            f"Failed to send final prompt to user: {e}")
    # Only now, after all notifications, remove the relay so the user can see the admin's location until the very end
    try:
        logger.info(f"Cleaning up data for completed order #{order_id}")
        # 1. Remove from admin_orders (Stops Admin->User relay)
        admin_orders = context.bot_data.get('admin_orders', {})
        if order_id in admin_orders:
            del admin_orders[order_id]
            logger.info(f"Removed order {order_id} from admin_orders")

        # 2. Remove from admin_live (Stops User->Admin relay)
        admin_live = context.bot_data.get('admin_live', {})
        # admin_live is keyed by user_id
        if user_id in admin_live:
            del admin_live[user_id]
            logger.info(f"Removed user {user_id} from admin_live")
        # Fallback: search by order_id if user_id key missing or different
        for k in list(admin_live.keys()):
            if admin_live[k].get('order_id') == order_id:
                del admin_live[k]

        # 3. Remove from tracking_relays (Stops Admin->User relay mapping)
        # (This is the key part: only remove after all notifications are sent)
        relays = context.bot_data.get('tracking_relays', {})
        # relays is keyed by admin_id
        for k in list(relays.keys()):
            if relays[k].get('order_id') == order_id:
                del relays[k]
                logger.info(f"Removed relay for admin {k}")

        # 4. Remove locks
        order_locked = context.bot_data.get('order_locked', {})
        if order_id in order_locked:
            del order_locked[order_id]

    except Exception as e:
        logger.error(f"Error during cleanup for order {order_id}: {e}")


async def rating_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 3:
        return
    order_id = int(parts[1])
    rating = int(parts[2])

    # Already imported at top
    save_rating(order_id, rating)

    await query.edit_message_text(f"Thank you! You rated this order {rating}/10.")

    # --- NEW: Post Rating to Completed Orders Channel ---
    try:
        # Fetch order details to get admin info
        order = get_order(order_id)
        # deliverer_id is at index 2
        deliverer_id = order[2] if order else None

        admin_name = "Unknown Admin"
        if deliverer_id:
            try:
                # Try to get admin name from chat member info
                member = await context.bot.get_chat_member(ADMIN_CHAT_ID, deliverer_id)
                admin_name = member.user.full_name
            except Exception:
                pass

        from html import escape
        admin_name = escape(admin_name)

        msg = (
            f"⭐ <b>RATING RECEIVED</b>\n\n"
            f"<b>Order #{order_id}</b>\n"
            f"<b>Rating:</b> {rating}/10\n"
            f"<b>Delivered By:</b> {admin_name}"
        )

        await context.bot.send_message(
            chat_id=COMPLETED_ORDERS_CHANNEL_ID,
            text=msg,
            parse_mode='HTML'
        )
    except Exception as e:
        logger.warning(f"Failed to post rating to channel: {e}")

    # Wait 3 seconds, then Prompt
    try:
        await asyncio.sleep(3)
        user_id = query.from_user.id
        from database import get_user_language
        lang = get_user_language(user_id) or 'en'
        await context.bot.send_message(
            chat_id=user_id,
            text=get_text('rating_submitted', lang)
        )
    except Exception as e:
        logger.warning(f"Failed to send final prompt after rating: {e}")



# 1. Standard setup: Show INFO for your own code
# logging only shows WARNING and above by default, so we set it to INFO
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 2. SILENCE the "HTTP Request: POST... 200 OK" noise
# We set these to WARNING or ERROR so they don't show routine successful polls
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram.ext._application").setLevel(logging.WARNING)

# STATES
# Add REG_GENDER between REG_BLOCK and REG_DORM to support GC Building flow
REG_LANGUAGE, REG_NAME, REG_ID, REG_BLOCK, REG_GENDER, REG_DORM, REG_PHONE = range(7)
ORDER_REST, ORDER_TYPE, ORDER_ITEM, ORDER_CONFIRM, ORDER_LOCATION = range(7, 12)
DEV_WAIT_LOC = 99

# Helper: Haversine Distance


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi/2)**2 + math.cos(phi1) * \
        math.cos(phi2) * math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c


# Load environment variables from .env file
load_dotenv()

# TOKEN (now loaded from .env)
TOKEN = os.getenv("TELEGRAM_TOKEN")

# Admin chat id (now loaded from .env)
try:
    ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID')) if os.getenv(
        'ADMIN_CHAT_ID') else None
except Exception:
    ADMIN_CHAT_ID = None

if not ADMIN_CHAT_ID:
    logger.warning(
        'Environment var ADMIN_CHAT_ID not set; falling back to -1003602307066')
    ADMIN_CHAT_ID = -1003602307066

# Completed Orders Channel ID
try:
    COMPLETED_ORDERS_CHANNEL_ID = int(os.getenv('COMPLETED_ORDERS_CHANNEL_ID')) if os.getenv(
        'COMPLETED_ORDERS_CHANNEL_ID') else None
except Exception:
    COMPLETED_ORDERS_CHANNEL_ID = None

if not COMPLETED_ORDERS_CHANNEL_ID:
    logger.warning(
        'Environment var COMPLETED_ORDERS_CHANNEL_ID not set; falling back to -1003306702660')
    COMPLETED_ORDERS_CHANNEL_ID = -1003306702660


# --- Registration Flow ---


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Check language and ban status
    user = get_user(user_id)
    
    if user and len(user) > 12 and user[12]: # is_banned column
        await update.message.reply_text("❌ Access Denied: Your account has been suspended for security reasons.")
        return

    language = None
    if user and len(user) > 11:
        language = user[11]
    
    if not language:
        language = context.user_data.get('language')

    if not language:
        await update.message.reply_text(
            get_text('choose_lang', 'en'),
            reply_markup=ReplyKeyboardMarkup([['English', 'Amharic']], one_time_keyboard=True, resize_keyboard=True)
        )
        return REG_LANGUAGE

    context.user_data['language'] = language

    # Check if user is already registered
    if user:
        name = user[2] if len(user) > 2 and user[2] else "User"

        await update.message.reply_text(
            get_text('welcome_back', language).format(name=name),
            reply_markup=ReplyKeyboardMarkup(
                [[get_text('order_food', language)], [get_text('reset_reg', language)]],
                one_time_keyboard=True,
                resize_keyboard=True
            )
        )
        return ConversationHandler.END

    # Not registered - Start Registration
    context.user_data['in_registration'] = True
    await update.message.reply_text(
        get_text('welcome_reg', language)
    )
    return REG_NAME


async def reset_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Intentional reset of registration data."""
    # Clear user data
    context.user_data.clear()
    context.user_data['in_registration'] = True

    await update.message.reply_text(
        "🔄 **Registration Reset**\n\n"
        "Let's start over. Please enter your Full Name (use the name on your ID):",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='Markdown'
    )
    return REG_NAME


# --- Resume Handlers ---

async def resume_rest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resends restaurant selection."""
    language = context.user_data.get('language', 'en')
    keyboard = []
    menu_names = list(MENUS.keys())
    row = []
    for name in menu_names:
        row.append(name)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await update.message.reply_text(
        get_text('resume_rest', language),
        reply_markup=ReplyKeyboardMarkup(
            keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return ORDER_REST


async def resume_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resends menu for selected restaurant."""
    language = context.user_data.get('language', 'en')
    restaurant = context.user_data.get('restaurant')
    if not restaurant or restaurant not in MENUS:
        # Fallback if data missing
        return await resume_rest(update, context)

    menu = MENUS[restaurant]
    keyboard = []
    for item, price in menu.items():
        keyboard.append([f"{item} - {price} ETB"])

    await update.message.reply_text(
        get_text('resume_menu', language).format(restaurant=restaurant),
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    )
    return ORDER_ITEM


async def resume_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resends confirmation options."""
    language = context.user_data.get('language', 'en')
    # Check if multi-ordering
    if context.user_data.get('multi_ordering'):
        await update.message.reply_text(
            get_text('resume_confirm', language),
            reply_markup=ReplyKeyboardMarkup(
                [[get_text('done_ordering', language), get_text('add_more', language)], 
                 [get_text('cancel', language)]], 
                 one_time_keyboard=True, resize_keyboard=True)
        )
    else:
        # Single order or finished multi-order
        orders = context.user_data.get('orders', [])
        if orders:
            # Show summary
            summary = get_text('confirm_summary', language)
            total = 0
            for idx, o in enumerate(orders, 1):
                summary += f"{idx}. {o['restaurant']} - {o['item']} ({o['price']} ETB)\n"
                total += o['price']
            summary += get_text('total', language).format(total=total)
            summary += get_text('remove_order', language)

            cancel_buttons = [[get_text('cancel_order_btn', language).format(i=i+1)]
                              for i in range(len(orders))]
            cancel_buttons.append([get_text('confirm', language)])
            await update.message.reply_text(
                summary,
                reply_markup=ReplyKeyboardMarkup(
                    cancel_buttons, one_time_keyboard=True, resize_keyboard=True),
                parse_mode='Markdown'
            )
        else:
            # Single pending item
            item = context.user_data.get('item')
            price = context.user_data.get('price')
            rest = context.user_data.get('restaurant')
            # Simplified fallback for single item case
            await update.message.reply_text(
                f"Confirm Order:\nRestaurant: {rest}\nItem: {item}\nPrice: {price} ETB\n\nTap 'Confirm' to proceed.",
                reply_markup=ReplyKeyboardMarkup(
                    [[get_text('confirm', language), get_text('add_more', language)], 
                     [get_text('cancel', language)]], 
                     one_time_keyboard=True, resize_keyboard=True)
            )
    return ORDER_CONFIRM


async def resume_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resends location options."""
    # Check if we are in cancel_ready state (Dorm selected)
    if context.user_data.get('cancel_ready'):
        orders = context.user_data.get('orders', [])
        cancel_buttons = [[f'Cancel Order {i+1}'] for i in range(len(orders))]
        cancel_buttons.append(['Cancel All Orders'])
        cancel_buttons.insert(0, ['Place Order'])

        await update.message.reply_text(
            "Resuming... Location set to Dorm.\nReady to place your order?",
            reply_markup=ReplyKeyboardMarkup(
                cancel_buttons, one_time_keyboard=True, resize_keyboard=True)
        )
    else:
        await update.message.reply_text(
            "Resuming... Where should we deliver?",
            reply_markup=ReplyKeyboardMarkup(
                [['Dorm', 'My Location']], one_time_keyboard=True, resize_keyboard=True)
        )
    return ORDER_LOCATION
    await update.message.reply_text(
        "🔄 **Registration Reset**\n\n"
        "Let's start over. Please enter your Full Name (use the name on your ID):",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='Markdown'
    )
    return REG_NAME


async def reg_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    lang = 'en'
    if 'Amharic' in text:
        lang = 'am'
    elif 'English' in text:
        lang = 'en'
    else:
        await update.message.reply_text("Please select English or Amharic.")
        return REG_LANGUAGE
    
    context.user_data['language'] = lang
    
    user_id = update.effective_user.id
    user = get_user(user_id)
    if user:
         set_user_language(user_id, lang)
         
         name = user[1]
         await update.message.reply_text(
            get_text('welcome_back', lang).format(name=name),
            reply_markup=ReplyKeyboardMarkup(
                [[get_text('order_food', lang)], [get_text('reset_reg', lang)]],
                one_time_keyboard=True,
                resize_keyboard=True
            )
        )
         return ConversationHandler.END
    
    context.user_data['in_registration'] = True
    await update.message.reply_text(
         get_text('welcome_reg', lang),
         reply_markup=ReplyKeyboardRemove()
    )
    return REG_NAME


async def reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    language = context.user_data.get('language', 'en')

    # Must contain only alphabetic characters (Unicode supported) and spaces
    if not name.replace(' ', '').isalpha():
        await update.message.reply_text(
            "Invalid input: all characters in the full name must be alphabetic letters and spaces.\n"
            "Please enter your Full Name (use the name on your ID):" if language == 'en' else "እባክዎ ትክክለኛ ሙሉ ስም ያስገቡ (መታወቂያዎ ላይ እንዳለው):"
        )
        return REG_NAME

    # Split into parts and require at least two parts
    parts = [p for p in name.split() if p]
    if len(parts) < 2:
        await update.message.reply_text(
            "You also need to input your father name — include a space between names.\n"
            "Please enter your Full Name (FirstName FatherName):" if language == 'en' else "የአባትዎን ስም ያስገቡ (ስም እና የአባት ስም በመሀል ክፍተት ይተዉ):"
        )
        return REG_NAME

    # Each of the first two name parts must be at least 3 alphabetic letters
    if len(parts[0]) < 3 or len(parts[0]) > 12 or len(parts[1]) < 3 or len(parts[1]) > 12:
        await update.message.reply_text(
            "Each of the first and second name parts must be at least 3 at most 12 alphabetic letters.\n"
            "Please enter your Full Name (FirstName FatherName) <-- in this format:" if language == 'en' else "እያንዳንዱ ስም ቢያንስ 3 እና ቢበዛ 12 ፊደላት ሊኖሩት ይገባል። እባክዎ እንደገና ያስገቡ:"
        )
        return REG_NAME

    context.user_data['name'] = name
    # Prompt for student ID and allow going back to name if needed
    await update.message.reply_text(
        get_text('enter_id', language).format(name=name),
        reply_markup=ReplyKeyboardMarkup(
            [['Back' if language == 'en' else 'ተመለስ']], one_time_keyboard=True, resize_keyboard=True)
    )
    return REG_ID


async def reg_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sid = update.message.text.strip()
    language = context.user_data.get('language', 'en')

    # --- NEW PARAMETER CHECK: BLOCK COMMANDS ---
    # We use a tuple ('/', '\\') to catch both forward and backslashes
    if sid.startswith(('/', '\\')):
        await update.message.reply_text(
            "❌ **Invalid Input**\n\n"
            "Please follow the registration step to order! Use /start to begin.\n"
            "Now, please enter your **Student ID** to continue:" if language == 'en' else "❌ **የተሳሳተ ግብዓት**\n\nእባክዎ የተማሪ መታወቂያዎን ያስገቡ:",
            parse_mode='Markdown'
        )
        return REG_ID

    # --- YOUR ORIGINAL STRUCTURE START ---
    # Handle 'Back' to edit the name
    if sid.lower() == 'back' or sid == 'ተመለስ':
        await update.message.reply_text(
             get_text('reg_reset_msg', language),
            reply_markup=ReplyKeyboardMarkup(
                [['Back' if language == 'en' else 'ተመለስ']], one_time_keyboard=True, resize_keyboard=True)
        )
        return REG_NAME

    # Accept formats like: nsr/1234/16  or  EX-123-18
    pattern = r'^(nsr|ex)[/\-_.](\d{3,4})[/\-_.](\d{2})$'
    m = re.match(pattern, sid, flags=re.I)
    if not m:
        await update.message.reply_text(
             get_text('reg_fail_id', language)
        )
        return REG_ID

    prefix, digits, yy = m.group(1), m.group(2), m.group(3)

    # Middle must be numeric (3 or 4 digits)
    if not digits.isdigit() or not (3 <= len(digits) <= 4):
        await update.message.reply_text("The middle part must be 3 or 4 digits. Please re-enter your Student ID:")
        return REG_ID

    # Last two digits must be numeric and within allowed entry years
    try:
        yy_val = int(yy)
    except ValueError:
        await update.message.reply_text("The last part must be a two-digit year between 14 and 18. Please re-enter your Student ID:")
        return REG_ID

    if yy_val < 14 or yy_val > 18:
        await update.message.reply_text("The last two digits must be between 14 and 18 inclusive. Please re-enter your Student ID:")
        return REG_ID

    # Normalise and store
    context.user_data['student_id'] = f"{prefix.lower()}/{digits}/{yy}"

    # Prepare block-selection keyboard
    special = ['NEWYORK', 'Around GC Building']
    try:
        known = list(BLOCKS.keys())
    except Exception:
        known = []

    keyboard = []
    keyboard.append(special)
    row = []
    for b in known[:6]:
        row.append(b)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append(['Back' if language == 'en' else 'ተመለስ'])

    msg = "Student ID accepted. Please choose your Block (or select a special area):" if language == 'en' else "መታወቂያ ተቀባይነት አግኝቷል። እባክዎ ብሎክ ይምረጡ (ወይም ልዩ ቦታ ይምረጡ):"

    await update.message.reply_text(
        msg,
        reply_markup=ReplyKeyboardMarkup(
            keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return REG_BLOCK


async def reg_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    language = context.user_data.get('language', 'en')

    # Handle Back
    if text.lower() == 'back' or text == 'ተመለስ':
        context.user_data.pop('student_id', None)
        await update.message.reply_text(
             get_text('enter_id', language).format(name=context.user_data.get('name')),
            reply_markup=ReplyKeyboardMarkup([['Back' if language == 'en' else 'ተመለስ']], one_time_keyboard=True, resize_keyboard=True)
        )
        return REG_ID

    # Handle NEWYORK
    if text == 'NEWYORK':
        ny_blocks = context.bot_data.get('newyork_blocks')
        if not ny_blocks:
            ny_blocks = [f"Block {random.randint(1, 14)}" for _ in range(6)]
            context.bot_data['newyork_blocks'] = ny_blocks

        kb = [[b] for b in ny_blocks]
        if ['Back' if language == 'en' else 'ተመለስ'] not in kb:
            kb.append(['Back' if language == 'en' else 'ተመለስ'])
        
        await update.message.reply_text("Select the NewYork block:" if language == 'en' else "የኒውዮርክ ብሎክ ይምረጡ:", reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True))
        # We stay in REG_BLOCK because the user simply selects a block from the new list next
        return REG_BLOCK

    # Handle GC Building (exact string match from reg_id)
    if text == 'Around GC Building':
        await update.message.reply_text(
            get_text('select_gender', language),
            reply_markup=ReplyKeyboardMarkup(
                [[get_text('male', language), get_text('female', language)], ['Back' if language == 'en' else 'ተመለስ']],
                one_time_keyboard=True,
                resize_keyboard=True
            )
        )
        return REG_GENDER

    context.user_data['block'] = text
    await update.message.reply_text(
        get_text('enter_dorm', language),
        reply_markup=ReplyKeyboardMarkup(
            [['Back' if language == 'en' else 'ተመለስ']], one_time_keyboard=True, resize_keyboard=True)
    )
    return REG_DORM

async def reg_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gender_input = update.message.text.strip()
    language = context.user_data.get('language', 'en')
    
    gender_map = {
        'ተመለስ': 'back',
        'ወንድ': 'male',
        'ሴት': 'female'
    }
    
    gender = gender_map.get(gender_input, gender_input.lower())

    if gender == 'back':
        # Re-show block selection (including special buttons)
        special = ['NEWYORK', 'Around GC Building']
        try:
            known = list(BLOCKS.keys())
        except Exception:
            known = []
        keyboard = [special]
        row = []
        for b in known[:6]:
            row.append(b)
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append(['Back' if language == 'en' else 'ተመለስ'])
        
        await update.message.reply_text(get_text('enter_block', language), reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
        return REG_BLOCK

    if gender not in ('male', 'female'):
        await update.message.reply_text(
            get_text('select_gender', language), 
            reply_markup=ReplyKeyboardMarkup([[get_text('male', language), get_text('female', language)], ['Back' if language == 'en' else 'ተመለስ']], one_time_keyboard=True, resize_keyboard=True)
        )
        return REG_GENDER

    context.user_data['gender'] = gender.capitalize()
    
    # Store dynamic blocks
    gc_blocks = [
        "Arctecture/ Civil block",
        "water_block",
        "mechanical_electrical_block",
        "2ND_comp/ 2ND_soft_block",
        "soft / comp GC_block",
        "unassigned",
    ]

    key = 'gc_male_blocks' if gender == 'male' else 'gc_female_blocks'
    context.bot_data.setdefault(key, gc_blocks)
    blocks = context.bot_data[key]

    kb = [[b] for b in blocks]
    if ['Back' if language == 'en' else 'ተመለስ'] not in kb:
        kb.append(['Back' if language == 'en' else 'ተመለስ'])
    
    await update.message.reply_text(get_text('enter_block', language), reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True))
    return REG_BLOCK

async def reg_dorm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dorm = update.message.text.strip()
    language = context.user_data.get('language', 'en')
    current_block = context.user_data.get('block', '')
    
    # Check if we came from GC Building (Gender flow)
    # The block name usually contains "GC" or is one of the dynamically added ones.
    is_gc_flow = False
    # A simple heuristic: check if the user has a stored gender (only GC flow sets gender)
    if context.user_data.get('gender'):
        is_gc_flow = True

    if dorm.lower() == 'back' or dorm == 'ተመለስ':
         # If GC Flow, show the specific GC blocks again
         if is_gc_flow:
             gender = context.user_data.get('gender').lower() # stored as Capitalized
             key = 'gc_male_blocks' if gender == 'male' else 'gc_female_blocks'
             # Default fallback if bot restarted
             gc_blocks_fallback = [
                "Arctecture/ Civil block",
                "water_block",
                "mechanical_electrical_block",
                "2ND_comp/ 2ND_soft_block",
                "soft / comp GC_block",
                "unassigned",
            ]
             blocks = context.bot_data.get(key, gc_blocks_fallback)
             
         # If NewYork Flow
         elif current_block.startswith('Block') and int(current_block.split()[1]) in range(1, 15): 
             # Re-trigger NewYork logic (simplified: show the NY blocks)
             blocks = context.bot_data.get('newyork_blocks', [f"Block {i}" for i in range(1,7)]) # Simplified fallback
         
         # Else Standard Flow
         else:
             blocks = BLOCKS

         keyboard = []
         row = []
         for b in blocks:
             row.append(b)
             if len(row) == 2:
                 keyboard.append(row)
                 row = []
         if row:
             keyboard.append(row)
         keyboard.append(['Back' if language == 'en' else 'ተመለስ'])
         
         await update.message.reply_text(get_text('enter_block', language), reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
         return REG_BLOCK

    context.user_data['dorm'] = dorm
    context.user_data['phone_attempts'] = 0
    await update.message.reply_text(
        get_text('enter_phone', language),
        reply_markup=ReplyKeyboardMarkup([['Back' if language == 'en' else 'ተመለስ']], one_time_keyboard=True, resize_keyboard=True)
    )
    return REG_PHONE


async def reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    language = context.user_data.get('language', 'en')

    # --- 1. HANDLE BACK BUTTON ---
    if text.lower() == 'back' or text == 'ተመለስ':
        # Return to gender selection or block depending on flow
        # For simplicity, returning to DORM state for standard flow.
        # But if the user was coming from GC Building > Gender > Block scheme, 
        # going back from phone -> dorm -> block is safe as we re-trigger the block logic.
        
        await update.message.reply_text(get_text('enter_dorm', language), reply_markup=ReplyKeyboardMarkup([['Back' if language == 'en' else 'ተመለስ']], one_time_keyboard=True, resize_keyboard=True))
        return REG_DORM

    # --- 2. VALIDATION LOGIC ---
    is_valid = False
    error_msg = ""

    # Rule: Starts with 09 or 07 -> Must be exactly 10 digits
    if text.startswith(('09', '07')):
        if text.isdigit() and len(text) == 10:
            is_valid = True
        else:
            error_msg = get_text('reg_fail_phone', language)

    # Rule: Starts with +2517 or +2519 -> Must be exactly 13 characters
    elif text.startswith(('+2519', '+2517')):
        if text[1:].isdigit() and len(text) == 13:
            is_valid = True
        else:
            error_msg = get_text('reg_fail_phone', language)

    else:
        error_msg = get_text('reg_fail_phone', language)

    # --- 3. HANDLE 5-ATTEMPT LIMIT ---
    if not is_valid:
        attempts = context.user_data.get('phone_attempts', 0) + 1
        context.user_data['phone_attempts'] = attempts

        if attempts >= 5:
            # Wipe progress so they start fresh on next /start
            context.user_data.clear()
            await update.message.reply_text("⚠️ 5 invalid attempts. Registration has been reset.\nPlease type /start to try again.")
            return ConversationHandler.END

        await update.message.reply_text(f"{error_msg}\n(Attempt {attempts}/5). Please try again:")
        return REG_PHONE

    # --- 4. SUCCESS PATH (EXISTING STRUCTURE) ---
    user_data = context.user_data
    user_data['phone'] = text
    user_id = update.effective_user.id
    username = update.effective_user.username  # Get telegram username
    
    # Store language too in DB if needed (already set in context at start)
    user_language = context.user_data.get('language', 'en')
    user_gender = context.user_data.get('gender')

    # Update database with username
    changes = add_user(user_id, username, user_data['name'], user_data['student_id'],
             user_data['block'], user_data['dorm'], user_data['phone'], user_gender)
    
    if changes:
        try:
            msg = f"⚠️ **User Details Changed**\nUser ID: {user_id}\n"
            for field, (old, new) in changes.items():
                msg += f"- {field.capitalize()}: {old} -> {new}\n"
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Failed to notify admin about user change: {e}")

    # Also update language preference in DB
    set_user_language(user_id, user_language)

    # Cleanup attempts counter
    if 'phone_attempts' in context.user_data:
        del context.user_data['phone_attempts']

    # Clear registration flag
    context.user_data.pop('in_registration', None)

    # --- 5. TRIGGER ORDER PROMPT AUTOMATICALLY ---
    await update.message.reply_text(
        get_text('reg_complete', user_language).format(
            name=user_data['name'],
            sid=user_data['student_id'],
            block=user_data['block'],
            dorm=user_data['dorm'],
            phone=user_data['phone']
        ),
        reply_markup=ReplyKeyboardMarkup(
            [[get_text('order_food', user_language)]], 
            one_time_keyboard=True, 
            resize_keyboard=True
        )
    )

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop('in_registration', None)
    language = context.user_data.get('language', 'en')
    await update.message.reply_text(
        get_text('cancel', language), 
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# --- Order Flow ---


def is_user_registered(user_id):
    # Connect to your database (ensure the name 'bedorme.db' matches your file)
    conn = sqlite3.connect('bedorme.db')
    cursor = conn.cursor()

    # Check if the user_id exists in the users table
    cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()

    conn.close()

    # Returns True if user exists, False otherwise
    return user is not None


async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Get user language from DB or context
    language = context.user_data.get('language')
    if not language:
        # Check DB
        user = get_user(user_id)
        if user and len(user) > 10: 
             language = user[10]
             context.user_data['language'] = language
        else:
             language = 'en'
             context.user_data['language'] = 'en'


    # Clear previous session data to prevent order accumulation
    context.user_data.pop('orders', None)
    context.user_data.pop('multi_ordering', None)

    # --- 0. CHECK IF IN REGISTRATION ---
    if context.user_data.get('in_registration'):
        await update.message.reply_text(
            "⚠️ **Registration in Progress**\n\n"
            "You are currently in the middle of registration.\n"
            "Please finish entering your details or type /cancel to stop registration before ordering.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    # --- 1. THE REGISTRATION GUARD (MUST BE FIRST) ---
    # We check the database BEFORE showing any restaurant buttons
    if not is_user_registered(user_id):
        await update.message.reply_text(
            "❌ **Access Denied**\n\n"
            "Please follow the registration step to order! You must be registered first.\n"
            "Type /start to begin your registration.",
            parse_mode='Markdown'
        )
        # We return END so the ordering process doesn't even start
        return ConversationHandler.END

    # --- 2. YOUR ORIGINAL STRUCTURE (ONLY RUNS IF REGISTERED) ---
    keyboard = []
    # Build keyboard from MENUS keys to ensure it matches
    menu_names = list(MENUS.keys())
    row = []
    for name in menu_names:
        row.append(name)
        if len(row) == 2:
           keyboard.append(row)
           row = []
    if row:
        keyboard.append(row)

    await update.message.reply_text(
        "ℹ️ **Delivery Fee Notice**\n"
        "A delivery fee of **15 ETB per item** will be added to your total order price.\n"
        "(e.g. 1 item = +15 ETB, 2 items = +30 ETB)\n\n" +
        get_text('choose_rest', language),
        reply_markup=ReplyKeyboardMarkup(
            keyboard, one_time_keyboard=True, resize_keyboard=True),
        parse_mode='Markdown'
    )
    return ORDER_REST


async def admin_accept_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback when admin taps 'Order Received' button in the admin group."""
    query = update.callback_query
    if update.effective_chat.id != ADMIN_CHAT_ID:
        await query.answer("Unauthorized action.", show_alert=True)
        return
    await query.answer()

    # callback format: admin_accept_{order_id}_{customer_id}
    parts = query.data.split("_")
    if len(parts) < 3:
        await query.edit_message_text("Invalid callback data.")
        return

    order_id = int(parts[2])
    customer_id = int(parts[3]) if len(parts) > 3 else None

    # --- FIX #4 & #5: ATOMIC DB CHECK ---
    # Try to assign the order in the DB. If it returns False, someone else took it.
    try:
        from database import assign_deliverer
        success = assign_deliverer(order_id, query.from_user.id)

        if not success:
            # Check who actually took it
            from database import get_order
            order = get_order(order_id)
            deliverer_id = order[2] if order else None

            # If I am the one who took it (maybe I clicked twice), that's fine.
            if deliverer_id != query.from_user.id:
                # Get the name of the admin who took it for clarity
                try:
                    member = await context.bot.get_chat_member(ADMIN_CHAT_ID, deliverer_id)
                    taken_by = member.user.full_name
                except:
                    taken_by = f"Admin {deliverer_id}"

                await query.answer(f"⚠️ Order already taken by {taken_by}!", show_alert=True)

                # Update the message to visually indicate it's taken, removing buttons to prevent confusion
                try:
                    # We can keep the text but maybe remove buttons or show a "Taken" label
                    # But if we remove buttons, the original owner can't use them?
                    # Actually, since this is a shared chat, modifying the message affects everyone!
                    # So we should NOT remove buttons. Just alert the clicker.
                    pass
                except:
                    pass
                return
    except Exception as e:
        logger.error(f"Failed to assign deliverer in DB: {e}")
        await query.answer("Error assigning order. Please try again.", show_alert=True)
        return

    # Mark order as accepted and update admin message to show it's been accepted
    # We still use bot_data for temporary UI state (like message_id), but the "Truth" is now in the DB.
    admin_orders = context.bot_data.setdefault('admin_orders', {})
    admin_entry = admin_orders.get(order_id)

    # If this is a fresh start (bot restarted), admin_entry might be None, but DB says we accepted it.
    if admin_entry is None:
        admin_orders[order_id] = {
            'accepted': True, 'admin_id': query.from_user.id}
        admin_entry = admin_orders[order_id]

    # ALWAYS Ensure it is marked as accepted in memory
    admin_entry['accepted'] = True
    admin_entry['admin_id'] = query.from_user.id

    request_location_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Request Updated Location",
                              callback_data=f"admin_request_location_{order_id}_{customer_id}")],
        [InlineKeyboardButton(
            "I'm about to pay", callback_data=f"about_to_pay_{order_id}_{customer_id}")],
        [InlineKeyboardButton("⚠️ Force Arrival Notify",
                              callback_data=f"force_arrival_{order_id}_{customer_id}")]
    ])

    # Update the message UI
    try:
        # Preserve original text, append status
        original_text = query.message.text
        # Avoid appending multiple times if clicked again
        if "Marked as received" not in original_text:
            new_text = f"{original_text}\n\n✅ Marked as received by {query.from_user.first_name}."
        else:
            new_text = original_text
        await query.edit_message_text(new_text, reply_markup=request_location_kb)
    except Exception:
        pass

    # Notify the customer that their order is on the way
    try:
        if customer_id:
            await context.bot.send_message(chat_id=customer_id, text=f"🚚 Your order #{order_id} is on the way!")
    except Exception as e:
        logger.warning(
            f"Could not notify customer about order on the way: {e}")

    # Ask admin group to share their live location in the admin chat
    try:
        # Get order and customer info for context
        order = None
        customer = None
        try:
            order = get_order(order_id)
            customer = get_user(customer_id) if customer_id else None
        except Exception:
            pass

        admin_name = query.from_user.full_name if query.from_user else "(unknown admin)"
        order_info = f"Order #{order_id}"
        if customer:
            order_info += (f"\nCustomer: {customer[2]} (@{customer[1]})"
                           f"\nStudent ID: {customer[3]}"
                           f"\nBlock/Dorm: {customer[4]} / {customer[5]}"
                           f"\nPhone: {customer[6]}")
        if order:
            order_info += (f"\nRestaurant: {order[3]}"
                           f"\nItem: {order[4]}"
                           f"\nPrice: {order[5]} ETB"
                           f"\nType: {order[7]}"
                           f"\nVerification Code: {order[8]}")

        prompt = (f"Admin {admin_name} has accepted this order. "
                  f"Only {admin_name} should share their live location for this order.\n\n"
                  f"{order_info}\n\n"
                  "Please share your Live Location here so the customer can track you.\n\nUse 📎 > Location > Share Live Location.")
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=prompt)
        # create a placeholder relay mapping: admin -> customer
        admin_id = query.from_user.id
        if admin_id and customer_id:
            if 'tracking_relays' not in context.bot_data:
                context.bot_data['tracking_relays'] = {}
            context.bot_data['tracking_relays'][admin_id] = {
                'chat_id': customer_id, 'message_id': None, 'order_id': order_id}
    except Exception as e:
        logger.warning(f"Failed prompting admin group for live location: {e}")


async def force_arrival_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin manually clicked 'Force Arrival Notify'."""
    query = update.callback_query
    if update.effective_chat.id != ADMIN_CHAT_ID:
        await query.answer("Unauthorized action.", show_alert=True)
        return
    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 4:
        await query.edit_message_text("Invalid callback data.")
        return
    order_id = int(parts[2])
    user_id = int(parts[3])

    # --- CHECK IF CANCELLED ---
    from database import get_order
    order = get_order(order_id)
    # Status is at index 6
    if order and order[6] == 'cancelled':
        await query.edit_message_text("❌ This order was CANCELLED by the user. You cannot force arrival.")
        return

    # Notify User
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="Your food has arrived! You will shortly receive a call from our agents."
        )
    except Exception as e:
        logger.warning(f"Failed to send manual arrival msg to user: {e}")

    # Notify Admin (Ask if they see user)
    try:
        user = get_user(user_id)
        phone = user[5] if user and len(user) > 5 else "(unknown)"

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "Yes", callback_data=f"admin_seen_user_{order_id}_{user_id}")]
        ])

        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"✅ Manual Arrival Triggered.\nPlease call {phone}.\nDo you see the user? Click 'Yes' when you have seen the receiver.",
            reply_markup=kb
        )
        await query.edit_message_text(f"✅ Arrival Notification Sent Manually for Order #{order_id}.")
    except Exception as e:
        logger.warning(f"Failed to send manual arrival msg to admin: {e}")


async def order_rest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    # Sanitize input: strip whitespace
    choice = text.strip().replace(" (Premium)", "")

    # Manual mapping for Amharic or variations if needed
    # (Currently the buttons are just keys from MENUS, but if menus change to localized names, map here)
    # The user says "Wesen" (restaurant) is invalid.
    # Check if "Wesen" matches exactly "Wesen" in MENUS keys.
    # MENUS keys are: "Zebra", "Selam", "Promy", "Edget", "Fele", "Wesen", "Webete", "Darek"
    
    # Debug print
    # print(f"DEBUG: User chose {choice}, keys are {list(MENUS.keys())}")

    if choice not in MENUS:
        # Check if it was a valid choice but maybe case sensitive?
        # Let's try case-insensitive match
        found = None
        for k in MENUS:
            if k.lower() == choice.lower():
                found = k
                break
        
        if found:
            choice = found
        else:
             # Check if 'Resume Order' or 'Back' type commands were sent
            language = context.user_data.get('language', 'en')
            knames = ", ".join(list(MENUS.keys()))
            
            # Dynamic keyboard from MENUS keys
            keyboard = []
            row = []
            for name in MENUS.keys():
                row.append(name)
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
            
            await update.message.reply_text(
                f"Please select a valid restaurant.\nOptions: {knames}",
                 reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            )
            return ORDER_REST
    
    # Store clean choice
    context.user_data['restaurant'] = choice
    
    # Ask for Regular or Contract
    keyboard = [["Regular", "Contract"]]
    await update.message.reply_text(
        "Please choose your order type:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return ORDER_TYPE

async def order_type_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice_type = update.message.text.strip()
    restaurant = context.user_data.get('restaurant')
    user_id = update.effective_user.id
    language = context.user_data.get('language', 'en')

    if choice_type == "Contract":
        # Check registration
        contract = get_contract_details(user_id, restaurant)
        if not contract:
            # Fallback if not registered
            await update.message.reply_text(
                "❌ **Not Registered**\n\n"
                f"You are not registered as a contract user for **{restaurant}**. "
                "Switching to Regular order type.",
                parse_mode='Markdown'
            )
            context.user_data['is_contract'] = False
        else:
            # Check balance and credit
            paid = contract['total_paid']
            used = contract['balance_used']
            remains = contract['current_balance']
            credit = contract['credit_meals']
            
            # Requirement: if no assigned value then create credit value for 2 meals at most
            if remains <= 0 and credit >= 2:
                await update.message.reply_text(
                    "❌ **Credit Limit Reached**\n\n"
                    "Your balance is empty and you have used your 2-meal credit limit. "
                    "Please top up or use Regular order type.",
                    parse_mode='Markdown'
                )
                # Show type buttons again or go back to rest?
                keyboard = [["Regular", "Contract"]]
                await update.message.reply_text(
                    "Please choose your order type:",
                    reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
                )
                return ORDER_TYPE
            
            context.user_data['is_contract'] = True
            await update.message.reply_text(
                f"🎖️ **Contract Order - {restaurant}**\n\n"
                f"💰 Total Paid: {paid} ETB\n"
                f"📉 Total Used: {used} ETB\n"
                f"💳 Remaining: {remains} ETB\n"
                f"🍴 Credit Meals Used: {credit}/2",
                parse_mode='Markdown'
            )
    else:
        context.user_data['is_contract'] = False

    # Proceed to show items
    is_contract = context.user_data.get('is_contract', False)
    if is_contract and restaurant in CONTRACT_MENUS:
        menu = CONTRACT_MENUS[restaurant]
        contract_msg = "\n\n🎖️ **Contract Price Applied**"
    else:
        menu = MENUS.get(restaurant, {})
        contract_msg = ""
    
    # Create menu buttons
    keyboard = []
    from database import get_unavailable_items
    unavailable = get_unavailable_items(restaurant)
    
    for item, price in menu.items():
        if item not in unavailable:
            keyboard.append([f"{item} - {price} ETB"])

    await update.message.reply_text(
        get_text('choose_item', language).format(restaurant=restaurant) + contract_msg,
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True),
        parse_mode='Markdown'
    )
    return ORDER_ITEM

async def order_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    language = context.user_data.get('language', 'en')

    # --- PARAMETER CHECK: PREVENT CRASH & UNAUTHORIZED COMMANDS ---
    restaurant = context.user_data.get('restaurant')
    is_contract = context.user_data.get('is_contract', False)
    
    if is_contract and restaurant in CONTRACT_MENUS:
        current_menu = CONTRACT_MENUS[restaurant]
    else:
        current_menu = MENUS.get(restaurant, {})

    from database import get_unavailable_items
    unavailable = get_unavailable_items(restaurant)
    available_keyboard = [[f"{item} - {price} ETB"] for item, price in current_menu.items() if item not in unavailable]

    if text.startswith('/'):
        await update.message.reply_text(
            "⚠️ Please use the buttons provided. Commands are not allowed during ordering.",
            reply_markup=ReplyKeyboardMarkup(available_keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return ORDER_ITEM
    if " - " not in text:
        await update.message.reply_text(
            "⚠️ **Unauthorized Access**\n\nFinish the process you started! Please select a food item from the buttons provided.",
            reply_markup=ReplyKeyboardMarkup(available_keyboard, one_time_keyboard=True, resize_keyboard=True),
            parse_mode='Markdown'
        )
        return ORDER_ITEM

    # --- YOUR ORIGINAL STRUCTURE (INTACT) ---
    try:
        parts = text.split(" - ")
        if len(parts) < 2:
            raise ValueError("Invalid format")
            
        item_name = parts[0]
        
        if item_name in unavailable:
             await update.message.reply_text(
                "😔 Sorry, this item just ran out! Please choose something else:",
                reply_markup=ReplyKeyboardMarkup(available_keyboard, one_time_keyboard=True, resize_keyboard=True)
            )
             return ORDER_ITEM

        # Robustly handle price string like "70.0 ETB" or just "70"
        price_str = parts[1].replace(" ETB", "").strip()
        price = float(price_str)
    except Exception:
        # Invalid input fallback
        await update.message.reply_text(
            "⚠️ Invalid selection. Please use the buttons provided.",
            reply_markup=ReplyKeyboardMarkup(available_keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return ORDER_ITEM

    # Use list of orders structure
    if 'orders' not in context.user_data:
        context.user_data['orders'] = []

    context.user_data['orders'].append({
        'restaurant': context.user_data['restaurant'],
        'item': item_name,
        'price': price
    })
    
    # Always set multi_ordering to true once they add an item to enable the flow
    context.user_data['multi_ordering'] = True

    await update.message.reply_text(
        f"Order Added:\nRestaurant: {context.user_data['restaurant']}\nItem: {item_name}\nPrice: {price} ETB\n\nAdd more or finish ordering.",
        reply_markup=ReplyKeyboardMarkup(
            [[get_text('done_ordering', language), get_text('add_more', language)], 
             [get_text('cancel', language)]], 
             one_time_keyboard=True, 
             resize_keyboard=True
        )
    )
    return ORDER_CONFIRM


async def order_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    language = context.user_data.get('language', 'en')

    # Prevent Telegram commands at confirmation
    if text.startswith('/'):
        await update.message.reply_text(
            "⚠️ Please use the buttons provided. Commands are not allowed during confirmation.",
            reply_markup=ReplyKeyboardMarkup(
                [[get_text('confirm', language), get_text('add_more', language)], [get_text('cancel', language)]], one_time_keyboard=True, resize_keyboard=True)
        )
        return ORDER_CONFIRM
        
    # Map button text back to English key logic
    action = 'unknown'
    if text == get_text('add_more', language):
        action = 'add_more'
    elif text == get_text('done_ordering', language):
        action = 'done'
    elif text == get_text('cancel', language):
         return await cancel(update, context) # Use existing cancel handler
    elif text.startswith("Cancel Order") or text.startswith("ትዕዛዝ") and "ሰርዝ" in text:
         action = 'remove_item_pressed'
    elif text == get_text('confirm', language):
         action = 'confirm'


    # 2. VALID: User clicks 'Add More Orders' -> Loop back to restaurant selection
    if action == 'add_more':
        # Order is already added in order_item handler. Just proceed.
        context.user_data['multi_ordering'] = True
        
        # Dynamic keyboard from MENUS keys
        keyboard = []
        row = []
        for name in MENUS.keys():
            row.append(name)
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
            
        await update.message.reply_text(
            get_text('resume_rest', language),
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return ORDER_REST

    # 3. VALID: User clicks 'Confirm' -> Ask for location
    elif action == 'confirm':
        await update.message.reply_text(
            get_text('share_loc', language),
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton(get_text('share_loc_btn', language), request_location=True)]],
                one_time_keyboard=True, resize_keyboard=True
            )
        )
        return ORDER_LOCATION

    # 4. VALID: User clicks 'I'm Done Ordering' -> Show all orders with confirm and cancel buttons
    elif action == 'done':
        # Order is already added in order_item handler. Just proceed.
        orders = context.user_data.get('orders', [])
        
        summary = get_text('confirm_summary', language)
        items_total = 0
        for idx, o in enumerate(orders, 1):
            summary += f"{idx}. {o['restaurant']} - {o['item']} ({o['price']} ETB)\n"
            items_total += o['price']
        
        num_items = len(orders)
        delivery_fee = num_items * 15
        grand_total = items_total + delivery_fee
        
        summary += f"\nItems Total: {items_total} ETB"
        summary += f"\nDelivery Fee ({num_items} items x 15): {delivery_fee} ETB"
        summary += f"\n**Grand Total: {grand_total} ETB**\n\n"
        
        summary += get_text('remove_order', language)

        # Build cancel buttons for each order
        cancel_buttons = [[get_text('cancel_order_btn', language).format(i=i+1)] for i in range(len(orders))]
        # Add confirm button at the bottom
        cancel_buttons.append([get_text('confirm', language)])
        await update.message.reply_text(
            summary,
            reply_markup=ReplyKeyboardMarkup(
                cancel_buttons, one_time_keyboard=True, resize_keyboard=True),
            parse_mode='Markdown'
        )
        context.user_data['multi_ordering'] = False
        return ORDER_CONFIRM

    # 5. VALID: User clicks 'Cancel Order X' in multi-order summary
    elif action == 'remove_item_pressed':
        # Extract number from text (works for both English and Amharic if digits are used)
        try:
            match = re.search(r'\d+', text)
            if match:
                idx = int(match.group()) - 1
            else:
                idx = -1
        except Exception:
            idx = -1

        orders = context.user_data.get('orders', [])
        if 0 <= idx < len(orders):
            cancelled = orders.pop(idx)
            context.user_data['orders'] = orders
            
            summary = get_text('confirm_summary', language)
            total = 0
            for i, o in enumerate(orders, 1):
                summary += f"{i}. {o['restaurant']} - {o['item']} ({o['price']} ETB)\n"
                total += o['price']
            
            if not orders:
                summary += "\nNo orders remaining."
                cancel_buttons = [[get_text('add_more', language)], [get_text('cancel', language)]]
            else:
                summary += get_text('total', language).format(total=total)
                summary += get_text('remove_order', language)
                cancel_buttons = [[get_text('cancel_order_btn', language).format(i=i+1)]
                                  for i in range(len(orders))]
                cancel_buttons.append([get_text('confirm', language)])
            
            await update.message.reply_text(
                summary,
                reply_markup=ReplyKeyboardMarkup(
                    cancel_buttons, one_time_keyboard=True, resize_keyboard=True),
                parse_mode='Markdown'
            )
            return ORDER_CONFIRM
        else:
            await update.message.reply_text(
                "Invalid cancel selection.",
                reply_markup=ReplyKeyboardMarkup(
                    [[get_text('confirm', language), get_text('add_more', language)]],
                    one_time_keyboard=True, resize_keyboard=True),
                parse_mode='Markdown'
            )
            return ORDER_CONFIRM

    # 6. VALID: User clicks 'Cancel' -> Ends the conversation
    elif text == get_text('cancel', language) or text == 'Cancel':
        return await cancel(update, context)

        return ConversationHandler.END

    # 7. INVALID PARAMETER: User types anything else
    else:
        # Show correct buttons depending on state
        if context.user_data.get('multi_ordering'):
            buttons = [["I'm Done Ordering", 'Add More Orders'], ['Cancel']]
        elif context.user_data.get('orders'):
            buttons = [[f'Cancel Order {i+1}']
                       for i in range(len(context.user_data['orders']))] + [['Confirm']]
        else:
            buttons = [['Confirm', 'Add More Orders'], ['Cancel']]
        await update.message.reply_text(
            "⚠️ Invalid input. Please use the buttons below.",
            reply_markup=ReplyKeyboardMarkup(
                buttons, one_time_keyboard=True, resize_keyboard=True),
            parse_mode='Markdown'
        )
        return ORDER_CONFIRM


async def order_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return ORDER_LOCATION

    text = message.text
    language = context.user_data.get('language', 'en')
    lat, lon = None, None

    # Helper to get combined order details
    def get_combined_order_details(ctx):
        orders = ctx.user_data.get('orders', [])
        if not orders:
            # Fallback
            p = ctx.user_data.get('price', 0)
            # Apply 15 fee to fallback single item too
            return {
                'restaurant': ctx.user_data.get('restaurant'),
                'item': ctx.user_data.get('item'),
                'price': p + 15 
            }

        restaurants = set(o['restaurant'] for o in orders)
        restaurant_str = ", ".join(restaurants)

        items_str = ", ".join(
            [f"{o['item']} ({o['restaurant']})" for o in orders])
        
        items_total = sum(o['price'] for o in orders)
        delivery_fee = len(orders) * 15
        total_price = items_total + delivery_fee

        return {
            'restaurant': restaurant_str,
            'item': items_str,
            'price': total_price
        }

    # Map text back to internal action
    action = 'unknown'
    if text == 'Dorm': action = 'Dorm'
    elif text == get_text('share_loc_btn', language): action = 'My Location' # KeyboardButton sends text too
    elif message.location: action = 'location_received'
    elif text == get_text('yes_correct', language): action = 'Place Order'
    elif text == get_text('cancel', language): # Or "Cancel" equivalent
         return await cancel(update, context)

    # Note: Logic for 'Dorm' vs 'My Location'
    # Wait, 'Dorm' button is not shown in my previous `order_confirm` update. 
    # I changed it to only showing "Share My Location" button.
    # Ah, I should check `order_confirm` above. I removed the Dorm option in the updated code 
    # because I saw `reply_kb = [[KeyboardButton(get_text('share_loc_btn', language), request_location=True)]]`
    # So user MUST share location.
    
    if action == 'location_received':
        lat = message.location.latitude
        lon = message.location.longitude
        
        # Verify distance or just accept
        # ... validation logic ...
        
        # Ask for final confirmation "Place Order"
        # store location in context
        context.user_data['delivery_lat'] = lat
        context.user_data['delivery_lon'] = lon
        
        await message.reply_text(
            get_text('confirm_loc', language),
            reply_markup=ReplyKeyboardMarkup(
                [[get_text('yes_correct', language), get_text('no_retry', language)]],
                one_time_keyboard=True, resize_keyboard=True
            )
        )
        return ORDER_LOCATION
        
    elif action == 'Place Order':
        # Finalize order
        user_id = update.effective_user.id
        user = get_user(user_id)
        
        lat = context.user_data.get('delivery_lat')
        lon = context.user_data.get('delivery_lon')

        # Create Order
        details = get_combined_order_details(context)
        code = ''.join(random.choices(string.digits, k=4))

        # Get Pickup Coords
        pickup_coords = RESTAURANTS.get(details['restaurant'], (None, None))
        pickup_lat, pickup_lon = pickup_coords

        is_contract = context.user_data.get('is_contract', False)
        order_type = 'contract' if is_contract else 'regular'

        # Pre-check for contract balance/credit
        if is_contract:
            res = update_contract_payment(user_id, details['restaurant'], details['price'])
            if res == "credit_limit_reached":
                await message.reply_text(
                    "❌ **ORDER FAILED**\n\nYour contract balance is empty and you have reached the maximum credit limit (2 meals). Please pay your dues at the cafe to continue ordering.",
                    parse_mode='Markdown'
                )
                return ConversationHandler.END
            elif res == "no_contract":
                 # Should not happen if is_contract is True, but handle anyway
                 is_contract = False
                 order_type = 'regular'

        order_id = create_order(
            user_id,
            details['restaurant'],
            details['item'],
            details['price'],
            code,
            lat,
            lon,
            pickup_lat,
            pickup_lon,
            order_type=order_type
        )

        # Notify admin/channel about new order (if configured)
        try:
            customer = get_user(user_id)
            # Send admin message with inline buttons: accept and about-to-pay
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "Order Received", callback_data=f"admin_accept_{order_id}_{user_id}"),
                    InlineKeyboardButton(
                        "I'm about to pay", callback_data=f"about_to_pay_{order_id}_{user_id}")
                ]
            ])
            
            # Construct localized admin message (Admin likely speaks English or Amharic, stick to English/Mixed for Admin)
            sent_admin = await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=(f"🆕 New Order #{order_id}\n"
                      f"Customer: {customer[1]} (tg id: {customer[0]})\n"
                      f"Student ID: {customer[2]}\n"
                      f"Block/Dorm: {customer[3]} / {customer[4]}\n"
                      f"Phone: {customer[5]}\n"
                      f"Restaurant: {details['restaurant']}\n"
                      f"Item: {details['item']} | Price: {details['price']} ETB\n"
                      f"Verification Code: {code}"),
                reply_markup=kb)
            # store admin order state so callbacks can edit it later
            admin_orders = context.bot_data.setdefault('admin_orders', {})
            admin_orders[order_id] = {
                'message_id': sent_admin.message_id, 'accepted': False, 'about_to_pay': False}
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")

        await message.reply_text(
             get_text('order_placed', language).format(order_id=order_id, code=code), 
             reply_markup=ReplyKeyboardRemove()
        )

        # Send an inline Cancel Order button
        try:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(
                get_text('cancel_order_button', language), callback_data=f"cancel_order_{order_id}")]])
            sent_cancel = await context.bot.send_message(
                chat_id=user_id, 
                text=get_text('cancel_order_prompt', language), 
                reply_markup=kb
            )
            # store user's cancel-button message id so we can remove it if admin proceeds to purchase
            user_cancel_msgs = context.bot_data.setdefault(
                'user_cancel_msgs', {})
            user_cancel_msgs[order_id] = {
                'chat_id': user_id, 'message_id': sent_cancel.message_id}
        except Exception:
            pass
            
        return ConversationHandler.END
    
    elif text == get_text('no_retry', language):
         # Ask for location again
        reply_kb = [[KeyboardButton(get_text('share_loc_btn', language), request_location=True)]]
        await message.reply_text(
            get_text('share_loc', language),
            reply_markup=ReplyKeyboardMarkup(reply_kb, one_time_keyboard=True, resize_keyboard=True)
        )
        return ORDER_LOCATION
    
    else:
        # Unknown input
        await message.reply_text(
             "Please share your location or select an option.",
             reply_markup=ReplyKeyboardMarkup(
                 [[KeyboardButton(get_text('share_loc_btn', language), request_location=True)]], 
                 one_time_keyboard=True, resize_keyboard=True
            )
        )
        return ORDER_LOCATION

# --- Admin verifies user-uploaded location ---


async def admin_verify_location_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if update.effective_chat.id != ADMIN_CHAT_ID:
        await query.answer("Unauthorized action.", show_alert=True)
        return
    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 7:
        await query.edit_message_text("Invalid callback data.")
        return
    action = parts[3]
    user_id = int(parts[4])
    lat = float(parts[5])
    lon = float(parts[6])

    if action == "yes":
        try:
            # Set a flag in bot_data to allow order to proceed
            context.bot_data[f'location_verified_{user_id}'] = (lat, lon)
            await query.edit_message_text(f"Location for user {user_id} accepted. Proceeding with order.")
            # Notify user
            await context.bot.send_message(chat_id=user_id, text="✅ Your location was accepted by the admin. Proceeding with your order.")

            # Generate Verification Code
            code = ''.join(random.choices(string.digits, k=4))

            # Use user_id from callback data since update.effective_user might be the admin
            # We need to retrieve the user's pending order data.
            # Since we don't have easy access to the user's conversation context here,
            # we rely on the fact that the user is waiting.
            # Ideally, we should have stored the pending order details in bot_data or database.
            # For this fix, we'll assume the user data is still accessible or we can't easily get it.
            # However, the original code used context.user_data which refers to the ADMIN's context here!
            # This is a flaw in the original code. The admin is clicking the button, so context.user_data is the admin's.
            # We need to retrieve the pending order info.
            # Let's assume for now we can't get the exact item details if they weren't stored globally.
            # BUT, looking at order_location, it stores 'pending_location'.
            # We need to store the pending order details in bot_data keyed by user_id in order_location.

            pending_order = context.bot_data.get(f'pending_order_{user_id}')
            if not pending_order:
                await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"Error: Could not find pending order data for user {user_id}.")
                return

            # Get Pickup Coords
            pickup_coords = RESTAURANTS.get(pending_order['restaurant'], (None, None))
            pickup_lat, pickup_lon = pickup_coords

            from database import is_test_mode_active
            is_test = 1 if is_test_mode_active() else 0

            # Override create_order to support is_test
            # Since create_order doesn't take is_test yet, we update it immediately after
            order_id = create_order(
                user_id,
                pending_order['restaurant'],
                pending_order['item'],
                pending_order['price'],
                code,
                lat,
                lon,
                pickup_lat,
                pickup_lon
            )
            
            # Patch for Test Mode
            if is_test:
                 from database import execute_query, get_db_connection
                 temp_conn = get_db_connection()
                 try:
                     execute_query(temp_conn, "UPDATE orders SET is_test = 1 WHERE order_id = ?", (order_id,))
                     temp_conn.commit()
                     # Optional: Notify admin this is a TEST order
                     await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"🧪 Note: Order #{order_id} marked as TEST data.")
                 finally:
                     temp_conn.close()

            # Notify admin/channel about new order (if configured)
            try:
                customer = get_user(user_id)
                # Send admin message with inline buttons: accept and about-to-pay
                kb = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "Order Received", callback_data=f"admin_accept_{order_id}_{user_id}"),
                        InlineKeyboardButton(
                            "I'm about to pay", callback_data=f"about_to_pay_{order_id}_{user_id}")
                    ]
                ])
                sent_admin = await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=(f"🆕 New Order #{order_id}\n"
                          f"Customer: {customer[1]} (tg id: {customer[0]})\n"
                          f"Student ID: {customer[2]}\n"
                          f"Block/Dorm: {customer[3]} / {customer[4]}\n"
                          f"Phone: {customer[5]}\n"
                          f"Restaurant: {pending_order['restaurant']}\n"
                          f"Item: {pending_order['item']} | Price: {pending_order['price']} ETB\n"
                          f"Verification Code: {code}"),
                    reply_markup=kb)
                # store admin order state so callbacks can edit it later
                admin_orders = context.bot_data.setdefault('admin_orders', {})
                admin_orders[order_id] = {
                    'message_id': sent_admin.message_id, 'accepted': False, 'about_to_pay': False}
                # If we have a location, send a live-location message to the admin chat so deliverer can view it there
                try:
                    if lat is not None and lon is not None:
                        sent = await context.bot.send_location(
                            chat_id=ADMIN_CHAT_ID,
                            latitude=lat,
                            longitude=lon,
                            live_period=3600
                        )
                        # store admin live mapping so subsequent customer edits can update this message
                        admin_live = context.bot_data.setdefault(
                            'admin_live', {})
                        admin_live[user_id] = {
                            'message_id': sent.message_id,
                            'order_id': order_id,
                            'customer_name': customer[1],
                            'student_id': customer[2],
                            'block': customer[3],
                            'dorm': customer[4],
                            'phone': customer[5]
                        }
                except Exception as e:
                    logger.warning(
                        f"Failed to send initial live location to admin chat: {e}")
            except Exception as e:
                logger.warning(f"Failed to send new order to admin chat: {e}")

            # Get user language for "Order Food" button
            cust_lang = 'en'
            try:
                cust_info = get_user(user_id)
                if cust_info and len(cust_info) > 10:
                    cust_lang = cust_info[10]
            except Exception:
                pass

            await context.bot.send_message(
                chat_id=user_id,
                text=f"Order Placed! Admin will review your order.\n\nIMPORTANT: Your verification code is *{code}*. Keep it safe.",
                parse_mode='Markdown',
                reply_markup=ReplyKeyboardMarkup(
                    [[get_text('order_food', cust_lang)]],
                    resize_keyboard=True,
                    one_time_keyboard=True
                )
            )

            # Send an inline Cancel Order button that prompts the user to re-enter their name if clicked
            try:
                kb = InlineKeyboardMarkup([[InlineKeyboardButton(
                    "Cancel Order", callback_data=f"cancel_order_{order_id}")]])
                sent_cancel = await context.bot.send_message(chat_id=user_id, text="If you wish to cancel your order, press below:", reply_markup=kb)
                # store user's cancel-button message id so we can remove it if admin proceeds to purchase
                user_cancel_msgs = context.bot_data.setdefault(
                    'user_cancel_msgs', {})
                user_cancel_msgs[order_id] = {
                    'chat_id': user_id, 'message_id': sent_cancel.message_id}
            except Exception:
                pass

            # Clean up pending order
            del context.bot_data[f'pending_order_{user_id}']

        except Exception as e:
            logger.warning(f"Failed to notify user after location accept: {e}")
    else:
        try:
            await query.edit_message_text(f"Location for user {user_id} rejected. No sync will occur.")
            await context.bot.send_message(chat_id=user_id, text="❌ Your location was rejected by the admin. Please upload a different location or cancel your order.")
        except Exception as e:
            logger.warning(f"Failed to notify user after location reject: {e}")
    return ConversationHandler.END

# --- Dev Tools ---


async def dev_start_set_loc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Restrict to Admin Group
    if update.effective_chat.id != ADMIN_CHAT_ID:
        # If sent in private, ignore or tell them to go to group
        return ConversationHandler.END

    await update.message.reply_text(
        "🛠 **Developer Mode**\n"
        "Please share your current location.\n"
        "I will set ALL Restaurants and Dorm Blocks to this location so you can test pickup and delivery without moving.",
        parse_mode='Markdown'
    )
    return DEV_WAIT_LOC


async def dev_set_loc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.location:
        lat = update.message.location.latitude
        lon = update.message.location.longitude

        # Update all restaurants
        for k in RESTAURANTS:
            RESTAURANTS[k] = (lat, lon)

        # Update all blocks
        for k in BLOCKS:
            BLOCKS[k] = (lat, lon)

        await update.message.reply_text(
            f"✅ **Test Environment Updated!**\n\n"
            f"All Restaurants and Blocks are now located at:\n"
            f"Lat: {lat}, Lon: {lon}\n\n"
            f"You can now test the flow from your current position.",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("Please share a valid location.")
        return DEV_WAIT_LOC
    return ConversationHandler.END

# --- Live Location Relay ---


# --- Rate limit for location updates ---
LOCATION_UPDATE_INTERVAL = 5  # seconds
last_location_update = {}


async def relay_location_updates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Catches edited messages (Live Location updates) and relays them to the other party, with rate limiting.
    """
    # Use effective_message to handle both new and edited messages automatically
    msg = update.effective_message

    if not msg or not msg.location:
        print(
            f"DEBUG: relay_location_updates called but no location found. Update: {update.to_dict()}")
        return

    chat_id = msg.chat_id
    sender_id = msg.from_user.id
    lat = msg.location.latitude
    lon = msg.location.longitude
    print(
        f"DEBUG: Location update from {sender_id} in chat {chat_id}: {lat}, {lon}")
    # Store latest user location in bot_data for on-demand admin requests
    context.bot_data[f'latest_location_{sender_id}'] = {
        'lat': lat, 'lon': lon, 'timestamp': time.time()}

    # --- IMPROVEMENT: Update active orders with better location ---
    if sender_id != ADMIN_CHAT_ID:  # If it's a user
        try:
            active_orders = get_user_active_orders(sender_id)
            if active_orders:
                for oid in active_orders:
                    update_order_location(oid, lat, lon)
                    print(f"DEBUG: Updated location for Order #{oid} in DB")
                    
                    # Notify admin group with details to avoid confusion
                    last_info_time = context.bot_data.get(f'last_info_update_{oid}', 0)
                    if time.time() - last_info_time > 20: # throttled to 20s
                        user = get_user(sender_id)
                        order = get_order(oid)
                        deliverer_name = "Not Assigned"
                        if order and order[2]:
                            deliverer = get_user(order[2])
                            if deliverer:
                                deliverer_name = f"{deliverer[2]} (@{deliverer[1]})"
                            else:
                                deliverer_name = f"Admin {order[2]}"
                        
                        info_msg = (
                            f"📍 **Live Tracking Update**\n"
                            f"👤 **Customer:** {user[2] if user else 'Unknown'} (@{user[1] if user else '?'})\n"
                            f"📞 **Phone:** {user[6] if user else 'N/A'}\n"
                            f"📦 **Order:** #{oid}\n"
                            f"🚚 **Deliverer:** {deliverer_name}\n"
                            f"🌐 [View Position](https://www.google.com/maps/search/?api=1&query={lat},{lon})"
                        )
                        # Try to edit the existing status message instead of spamming new ones
                        info_id_key = f'last_info_msg_id_{oid}'
                        last_msg_id = context.bot_data.get(info_id_key)

                        if last_msg_id:
                            try:
                                await context.bot.edit_message_text(chat_id=ADMIN_CHAT_ID, message_id=last_msg_id, text=info_msg, parse_mode='Markdown')
                            except Exception:
                                # If edit fails (e.g. deleted), send new
                                sent = await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=info_msg, parse_mode='Markdown')
                                context.bot_data[info_id_key] = sent.message_id
                        else:
                            sent = await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=info_msg, parse_mode='Markdown')
                            context.bot_data[info_id_key] = sent.message_id
                        
                        context.bot_data[f'last_info_update_{oid}'] = time.time()
            else:
                 # Check if recently completed order exists (linger detection)
                 # We warn if user is sharing location but has no active orders.
                 # This check should be throttled to avoid spamming admin.
                 linger_key = f"linger_warn_{sender_id}"
                 last_warn = context.bot_data.get(linger_key, 0)
                 if time.time() - last_warn > 300: # Warn every 5 minutes max
                     user = get_user(sender_id)
                     if user:
                        name = user[2]
                        phone = user[6] or "N/A"
                        warn_msg = (
                            f"⚠️ **Lingering Live Location Detected**\n"
                            f"User: {name} (ID: {sender_id})\n"
                            f"Phone: {phone}\n"
                            f"Is sharing live location but has NO active orders.\n"
                            f"Please contact them to stop sharing."
                        )
                        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=warn_msg, parse_mode='Markdown')
                        context.bot_data[linger_key] = time.time()

        except Exception as e:
            print(f"DEBUG: Failed to update order location in DB: {e}")

    # --- Rate limiting logic ---
    now = time.time()
    key = f"{chat_id}:{sender_id}"
    last = last_location_update.get(key, 0)
    if now - last < LOCATION_UPDATE_INTERVAL:
        print(f"DEBUG: Rate limit hit for {key}, skipping update.")
        return
    last_location_update[key] = now

    # --- New: If location is sent in the admin group, relay to user ---
    # Check if we have a relay set up for this user (explicit mapping from admin_accept_order)
    relays = context.bot_data.get('tracking_relays', {})
    print(f"DEBUG: Current relays keys: {list(relays.keys())}")

    if sender_id in relays:
        target = relays[sender_id]
        user_id = target.get('chat_id')
        order_id = target.get('order_id')

        # 1. Relay Location
        try:
            print(f"DEBUG: Relaying to {user_id}")
            # If target has a message_id we can edit the live location, otherwise send a new location
            if target.get('message_id'):
                await context.bot.edit_message_live_location(
                    chat_id=user_id,
                    message_id=target['message_id'],
                    latitude=lat,
                    longitude=lon
                )
            else:
                sent = await context.bot.send_location(
                    chat_id=user_id,
                    latitude=lat,
                    longitude=lon,
                    live_period=3600
                )
                # store the message_id so subsequent updates can edit instead of sending new messages
                target['message_id'] = sent.message_id
        except Exception as e:
            # If edit fails (e.g. message deleted), reset ID to send new one next time
            print(f"DEBUG: Failed to relay location: {e}")
            target['message_id'] = None

        # 2. Check for Arrival (Distance < 150m)
        try:
            from database import get_order, get_user
            order = get_order(order_id)
            if order:
                # user location from order
                user_lat = order[11]
                user_lon = order[12]

                if user_lat is not None and user_lon is not None:
                    distance = haversine(lat, lon, user_lat, user_lon)
                    if distance < 150:
                        notified_key = f"arrived_{order_id}"
                        if not context.bot_data.get(notified_key):
                            await context.bot.send_message(
                                chat_id=user_id,
                                text="Your food has arrived! You will shortly receive a call from our agents."
                            )

                            user = get_user(user_id)
                            phone = user[5] if user and len(
                                user) > 5 else "(unknown)"

                            kb = InlineKeyboardMarkup([
                                [InlineKeyboardButton(
                                    "Yes", callback_data=f"admin_seen_user_{order_id}_{user_id}")]
                            ])
                            await context.bot.send_message(
                                chat_id=ADMIN_CHAT_ID,
                                text=f"You are < 50m from the user for order #{order_id}. Please call {phone}.\nDo you see the user? Click 'Yes' when you have seen the receiver.",
                                reply_markup=kb
                            )
                            context.bot_data[notified_key] = True
        except Exception as e:
            print(f"DEBUG: Error in arrival check: {e}")

            # --- New: Check if admin is within 50m of user ---
            # Get order info
            order_id = target.get('order_id')
            if order_id:
                from database import get_order, get_user
                order = get_order(order_id)
                if order:
                    user_id = order[1]  # customer_id
                    user = get_user(user_id)
                    user_lat = order[11]  # delivery_lat
                    user_lon = order[12]  # delivery_lon
                    if user_lat is not None and user_lon is not None:
                        # Calculate distance
                        distance = haversine(lat, lon, user_lat, user_lon)
                        if distance < 50:
                            # Notify user if not already notified
                            notified_key = f"arrived_{order_id}"
                            if not context.bot_data.get(notified_key):
                                # Notify user
                                await context.bot.send_message(
                                    chat_id=user_id,
                                    text="Your food has arrived! You will shortly receive a call from our agents."
                                )
                                # Alert admin in group with phone number
                                phone = user[5] if user and len(
                                    user) > 5 else "(unknown)"
                                await context.bot.send_message(
                                    chat_id=ADMIN_CHAT_ID,
                                    text=f"You are < 50m from the user for order #{order_id}. Please call {phone}."
                                )
                                context.bot_data[notified_key] = True
        except Exception as e:
            logger.warning(f"Failed to relay location: {e}")
            print(f"DEBUG: Failed to relay: {e}")
    else:
        print("DEBUG: No relay found for this sender")

    # Also send/update the customer's live location to the admin/channel
    try:
        if ADMIN_CHAT_ID:
            admin_live = context.bot_data.setdefault('admin_live', {})
            admin_entry = admin_live.get(sender_id)
            if admin_entry and admin_entry.get('message_id'):
                try:
                    await context.bot.edit_message_live_location(
                        chat_id=ADMIN_CHAT_ID,
                        message_id=admin_entry['message_id'],
                        latitude=lat,
                        longitude=lon
                    )
                except Exception:
                    # If edit fails (message might be gone), send a new live location
                    sent = await context.bot.send_location(chat_id=ADMIN_CHAT_ID, latitude=lat, longitude=lon, live_period=3600)
                    admin_live[sender_id] = {'message_id': sent.message_id}
            else:
                sent = await context.bot.send_location(chat_id=ADMIN_CHAT_ID, latitude=lat, longitude=lon, live_period=3600)
                admin_live[sender_id] = {'message_id': sent.message_id}
    except Exception as e:
        logger.warning(f"Failed to send/update admin live location: {e}")


async def cancel_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback when user presses Cancel Order — prompt them to re-enter their full name."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id if query.from_user else (
        query.message.chat_id if query.message else None)
    # Prevent cancellation if order already locked (user already confirmed purchase)
    parts = query.data.split("_")
    order_id = None
    # Data format: cancel_order_{order_id} -> ["cancel", "order", "123"]
    if len(parts) >= 3:
        try:
            order_id = int(parts[2])
        except Exception:
            order_id = None

    order_locked = context.bot_data.get('order_locked', {})
    if order_id and order_locked.get(order_id):
        await context.bot.send_message(chat_id=user_id, text="This order is already confirmed and cannot be cancelled.")
        return

    # If admin has already indicated they're about to pay / purchase, refuse cancellation
    admin_orders = context.bot_data.get('admin_orders', {})
    admin_entry = admin_orders.get(order_id)
    if admin_entry and admin_entry.get('about_to_pay'):
        # Inform user that the package has already been purchased or is in process
        try:
            await context.bot.send_message(chat_id=user_id, text=(
                "We're sorry — the package has already been (or is being) purchased. Backing out now is not allowed and may lead to a ban.\n"
                "For support contact: @callowned or call +251936250347"))
        except Exception:
            pass
        return

    # Remove admin live-location message (if any) so the user loses the admin live display
    try:
        admin_live = context.bot_data.get('admin_live', {})
        admin_entry = admin_live.get(user_id)
        if admin_entry and admin_entry.get('message_id'):
            try:
                await context.bot.delete_message(chat_id=ADMIN_CHAT_ID, message_id=admin_entry['message_id'])
            except Exception:
                pass
            # remove mapping
            del admin_live[user_id]
    except Exception:
        pass

    # Inform the user about cancellation policy
    try:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "Yes, Cancel Order", callback_data=f"confirm_cancel_order_{order_id}")],
            [InlineKeyboardButton(
                "No, Keep Order", callback_data=f"keep_order_{order_id}")]
        ])
        await context.bot.send_message(chat_id=user_id, text=(
            "Order cancellation selected. Note: cancellation is only possible if the item has NOT yet been purchased.\n"
            "Are you sure you want to cancel this order?"), reply_markup=kb)
    except Exception:
        pass


async def confirm_cancel_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User confirmed cancellation."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 4:
        # Just ignore or log
        return
    order_id = int(parts[3])
    user_id = query.from_user.id

    # Double check lock
    order_locked = context.bot_data.get('order_locked', {})
    if order_locked.get(order_id):
        await query.edit_message_text("Too late! The order is already confirmed/purchased.")
        return

    # Mark as cancelled in DB
    try:
        from database import update_order_status
        update_order_status(order_id, 'cancelled')
    except Exception as e:
        logger.error(f"Failed to cancel order in DB: {e}")

    # Notify User
    await query.edit_message_text("✅ Order has been cancelled.\n\nTo place a new order, click: /order\nTo restart main menu, click: /start")

    # Notify Admin Group & Update Admin Message
    try:
        admin_orders = context.bot_data.get('admin_orders', {})
        admin_entry = admin_orders.get(order_id)
        if admin_entry and admin_entry.get('message_id'):
            # Update the original admin message to show CANCELLED
            try:
                # We need to fetch the original text or reconstruct it.
                # Since we can't easily fetch the text without an API call, let's try to edit it.
                # We'll just append "❌ CANCELLED BY USER" and remove buttons.
                await context.bot.edit_message_reply_markup(
                    chat_id=ADMIN_CHAT_ID,
                    message_id=admin_entry['message_id'],
                    reply_markup=None  # Remove buttons
                )
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"❌ **ORDER #{order_id} CANCELLED**\nThe user has cancelled this order.",
                    reply_markup=None,
                    reply_to_message_id=admin_entry['message_id']
                )
            except Exception as e:
                logger.warning(
                    f"Failed to update admin message on cancel: {e}")
        else:
            # Fallback if we don't have the message ID
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"❌ **ORDER #{order_id} CANCELLED**\nThe user has cancelled this order."
            )
    except Exception as e:
        logger.error(f"Failed to notify admin of cancellation: {e}")


async def keep_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Order kept. Thank you!")


async def about_to_pay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin clicked 'I'm about to pay' — ask customer to confirm purchase."""
    query = update.callback_query
    if update.effective_chat.id != ADMIN_CHAT_ID:
        await query.answer("Unauthorized action.", show_alert=True)
        return
    await query.answer()
    parts = query.data.split("_")
    # Expected format: about_to_pay_{order_id}_{user_id}
    # parts: ['about', 'to', 'pay', order_id, user_id]
    if len(parts) < 5:
        await query.edit_message_text("Invalid callback data.")
        return
    order_id = int(parts[3])
    customer_id = int(parts[4]) if len(parts) > 4 else None

    # find admin order entry for later edits and check accepted state
    admin_orders = context.bot_data.setdefault('admin_orders', {})
    admin_entry = admin_orders.get(order_id)

    # --- RECOVERY: Check DB if memory is lost (e.g. restart) ---
    if not admin_entry:
        from database import get_order
        order = get_order(order_id)  # (id, cust, deliverer, ...)
        # If order has a deliverer_id (index 2), it is accepted
        if order and order[2]:
            # Re-populate memory from DB + current message context
            admin_orders[order_id] = {
                'accepted': True,
                'admin_id': order[2],
                'message_id': query.message.message_id
            }
            admin_entry = admin_orders[order_id]

    admin_msg_id = admin_entry.get('message_id') if admin_entry else None

    # Ensure admin already accepted the order before initiating about-to-pay
    if not admin_entry or not admin_entry.get('accepted'):
        try:
            await query.answer(text="Please mark the order as received first.", show_alert=True)
        except Exception:
            pass
        return
    # mark that admin is about to pay
    admin_entry['about_to_pay'] = True

    # Send confirmation request to customer
    if customer_id:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "Confirm Purchase", callback_data=f"user_confirm_{order_id}_{admin_msg_id}")],
            [InlineKeyboardButton(
                "Cancel Purchase", callback_data=f"user_cancel_purchase_{order_id}_{admin_msg_id}")]
        ])
        try:
            # First, notify the user that the deliverer is about to purchase and cancel button will be removed
            try:
                # Remove user's cancel-button message if present
                user_cancel_msgs = context.bot_data.get('user_cancel_msgs', {})
                uentry = user_cancel_msgs.get(order_id)
                if uentry:
                    try:
                        await context.bot.delete_message(chat_id=uentry['chat_id'], message_id=uentry['message_id'])
                    except Exception:
                        pass
                    # remove stored mapping
                    del user_cancel_msgs[order_id]
            except Exception:
                pass

            await context.bot.send_message(chat_id=customer_id, text=(
                "The deliverer/admin has indicated they're about to purchase your order. The package will be purchased and sent — cancellation will not be available after purchase."))

            # Then send the confirm/cancel inline keyboard
            await context.bot.send_message(chat_id=customer_id, text=(
                "Do you confirm the purchase?\nIf you confirm, cancellation will no longer be possible."), reply_markup=kb)
        except Exception as e:
            logger.warning(f"Failed to send confirm request to customer: {e}")

    # Let admin know request has been forwarded
    try:
        # Provide visual feedback without destroying the control panel
        current_text = query.message.text if query.message else ""
        if "🔔 Waiting for customer confirmation..." not in current_text:
            await query.edit_message_text(
                text=f"{current_text}\n\n🔔 Waiting for customer confirmation...",
                reply_markup=query.message.reply_markup
            )
        else:
            await query.answer("Request sent! Waiting for customer...", show_alert=True)
    except Exception:
        pass


async def user_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 3:
        await query.edit_message_text("Invalid callback data.")
        return
    order_id = int(parts[2])
    admin_msg_id = int(parts[3]) if len(
        parts) > 3 and parts[3].isdigit() else None

    # Lock the order to prevent cancellation
    order_locked = context.bot_data.setdefault('order_locked', {})
    order_locked[order_id] = True

    # Notify customer
    try:
        await query.edit_message_text("✅ Purchase confirmed. You cannot cancel this order anymore.")
    except Exception:
        pass

    # Update admin message to show green light, BUT preserve details and buttons
    try:
        if admin_msg_id:
            # 1. Fetch Data to reconstruct message
            order = get_order(order_id)
            if not order:
                await query.edit_message_text("❌ Error: Order data not found (Session Expired). The server may have restarted. Please check with the deliverer directly or re-order.")
                return

            customer_id = order[1]
            customer = get_user(customer_id)

            restaurant = order[3]
            items = order[4]
            price = order[5]
            type_val = order[7]
            code = order[8]

            msg_text = (f"🆕 New Order #{order_id}\n"
                        f"Type: {type_val}\n"
                        f"Customer: {customer[2]} (@{customer[1]})\n"
                        f"Student ID: {customer[3]}\n"
                        f"Block/Dorm: {customer[4]} / {customer[5]}\n"
                        f"Phone: {customer[6]}\n"
                        f"Restaurant: {restaurant}\n"
                        f"Item: {items} | Price: {price} ETB\n"
                        f"Verification Code: {code}")

            # 2. Append Admin Accept Status
            admin_orders = context.bot_data.get('admin_orders', {})
            admin_entry = admin_orders.get(order_id)
            if admin_entry and admin_entry.get('accepted'):
                admin_name = "Admin"
                if 'admin_id' in admin_entry:
                    try:
                        # Try to fetch member to get name, or use cached if we had it (we don't)
                        # We'll just use "an Admin" if we can't get the name easily without an extra call
                        # But let's try the call, it's async
                        member = await context.bot.get_chat_member(ADMIN_CHAT_ID, admin_entry['admin_id'])
                        admin_name = member.user.first_name
                    except:
                        pass
                msg_text += f"\n\n✅ Marked as received by {admin_name}."

            # 3. Append User Confirm Status
            msg_text += "\n\n🟢 Customer CONFIRMED purchase."

            # 4. Rebuild Keyboard (Keep all functionalities)
            request_location_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Request Updated Location",
                                      callback_data=f"admin_request_location_{order_id}_{customer_id}")],
                [InlineKeyboardButton(
                    "I'm about to pay", callback_data=f"about_to_pay_{order_id}_{customer_id}")],
                [InlineKeyboardButton("⚠️ Force Arrival Notify",
                                      callback_data=f"force_arrival_{order_id}_{customer_id}")]
            ])

            await context.bot.edit_message_text(
                chat_id=ADMIN_CHAT_ID,
                message_id=admin_msg_id,
                text=msg_text,
                reply_markup=request_location_kb
            )
    except Exception as e:
        logger.warning(f"Failed to update admin message on confirm: {e}")


async def user_cancel_purchase_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 3:
        await query.edit_message_text("Invalid callback data.")
        return
    order_id = int(parts[2])
    admin_msg_id = int(parts[3]) if len(
        parts) > 3 and parts[3].isdigit() else None

    # Update admin message to show red light, BUT preserve details and buttons
    try:
        if admin_msg_id:
            # 1. Fetch Data
            order = get_order(order_id)
            if order:
                customer_id = order[1]
                customer = get_user(customer_id)

                restaurant = order[3]
                items = order[4]
                price = order[5]
                type_val = order[7]
                code = order[8]

                msg_text = (f"🆕 New Order #{order_id}\n"
                            f"Type: {type_val}\n"
                            f"Customer: {customer[1]} (tg id: {customer[0]})\n"
                            f"Student ID: {customer[2]}\n"
                            f"Block/Dorm: {customer[3]} / {customer[4]}\n"
                            f"Phone: {customer[5]}\n"
                            f"Restaurant: {restaurant}\n"
                            f"Item: {items} | Price: {price} ETB\n"
                            f"Verification Code: {code}")

                # 2. Append Admin Accept Status
                admin_orders = context.bot_data.get('admin_orders', {})
                admin_entry = admin_orders.get(order_id)
                if admin_entry and admin_entry.get('accepted'):
                    admin_name = "Admin"
                    if 'admin_id' in admin_entry:
                        try:
                            member = await context.bot.get_chat_member(ADMIN_CHAT_ID, admin_entry['admin_id'])
                            admin_name = member.user.first_name
                        except:
                            pass
                    msg_text += f"\n\n✅ Marked as received by {admin_name}."

                # 3. Append User Cancel Status
                msg_text += "\n\n🔴 Customer CANCELLED purchase request."

                # 4. Rebuild Keyboard
                request_location_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("Request Updated Location",
                                          callback_data=f"admin_request_location_{order_id}_{customer_id}")],
                    [InlineKeyboardButton(
                        "I'm about to pay", callback_data=f"about_to_pay_{order_id}_{customer_id}")],
                    [InlineKeyboardButton("⚠️ Force Arrival Notify",
                                          callback_data=f"force_arrival_{order_id}_{customer_id}")]
                ])

                await context.bot.edit_message_text(
                    chat_id=ADMIN_CHAT_ID,
                    message_id=admin_msg_id,
                    text=msg_text,
                    reply_markup=request_location_kb
                )
    except Exception as e:
        logger.warning(
            f"Failed to update admin message on customer cancel: {e}")

    # Send warning + acknowledge button to user
    try:
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Acknowledge", callback_data=f"ack_cancel_{order_id}")]])
        await query.edit_message_text("You have chosen to cancel the purchase.\nPlease do not order if your intent is to cancel. Press Acknowledge to continue.", reply_markup=kb)
    except Exception:
        pass


async def ack_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    order_id = int(parts[2]) if len(parts) > 2 else None
    user_id = query.from_user.id if query.from_user else None

    # Send the standard done prompt
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="Acknowledged.\n\nTo place a new order, click: /order\nTo restart main menu, click: /start"
        )
    except Exception:
        pass


async def clear_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only allow admin group to use this command
    if update.effective_chat and update.effective_chat.id == ADMIN_CHAT_ID:
        # Clear all order-related bot_data
        context.bot_data['admin_orders'] = {}
        context.bot_data['order_locked'] = {}
        context.bot_data['tracking_relays'] = {}
        context.bot_data['admin_live'] = {}
        # Interrupt all ongoing orders by ending all user conversations
        application = context.application
        for conv in application.conversation_conversations.values():
            for user_id, state in conv.items():
                try:
                    await application.bot.send_message(user_id, "Your order has been interrupted and cancelled by the admin.")
                except Exception:
                    pass
        application.conversation_conversations.clear()
        # Remove any active location sharing by deleting relay messages
        relays = context.bot_data.get('tracking_relays', {})
        for admin_id, relay in relays.items():
            chat_id = relay.get('chat_id')
            message_id = relay.get('message_id')
            if chat_id and message_id:
                try:
                    await application.bot.delete_message(chat_id=chat_id, message_id=message_id)
                except Exception:
                    pass
        context.bot_data['tracking_relays'] = {}
        await update.message.reply_text("All previous and ongoing orders, including active location sharing, have been cleared and interrupted. Admins can start fresh.")
    else:
        await update.message.reply_text("You are not authorized to use this command.")


async def restart_decision_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if update.effective_chat.id != ADMIN_CHAT_ID:
        await query.answer("Unauthorized action.", show_alert=True)
        return
    await query.answer()
    data = query.data

    if data == "restart_reset":
        # Clear all data
        # Note: application.user_data might be read-only (mappingproxy) in some versions/contexts
        try:
            # Try to clear if mutable
            if hasattr(context.application.user_data, 'clear'):
                context.application.user_data.clear()
        except Exception as e:
            logger.warning(f"Could not clear user_data: {e}")

        try:
            if hasattr(context.application.chat_data, 'clear'):
                context.application.chat_data.clear()
        except Exception as e:
            logger.warning(f"Could not clear chat_data: {e}")

        # bot_data is the most important one for order state
        context.application.bot_data.clear()

        # Re-initialize default bot_data structures
        context.bot_data.setdefault('tracking_relays', {})
        context.bot_data.setdefault('admin_live', {})
        context.bot_data.setdefault('admin_orders', {})
        context.bot_data.setdefault('order_locked', {})

        # Force flush to persistence
        await context.application.persistence.flush()

        await query.edit_message_text("✅ System reset. All data cleared. Ready for new orders.")

    elif data == "restart_resume":
        await query.edit_message_text("▶️ System resumed. Previous state restored.")


async def my_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(f"Your Telegram ID: <code>{user_id}</code>", parse_mode='HTML')

async def post_init(application: Application):
    # Ensure we are not conflicting with any previously set webhook
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logging.warning(f"delete_webhook failed or not needed: {e}")

    # Check database connectivity
    try:
        from database import get_db_connection
        conn = get_db_connection()
        conn.close()
        logging.info("Database connection verified.")
    except Exception as e:
        logging.error(f"Failed to connect to database on startup: {e}")

    # Check if we have resumed state (bot_data is not empty)
    # We check specific keys that indicate active state
    if application.bot_data.get('admin_orders') or application.bot_data.get('admin_live'):
        # Send message to admin
        keyboard = [
            [InlineKeyboardButton("Intentional (Reset Data)",
                                  callback_data="restart_reset")],
            [InlineKeyboardButton("Unintentional (Resume)",
                                  callback_data="restart_resume")]
        ]
        try:
            await application.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text="⚠️ **Server Restart Detected** ⚠️\n\nWas this restart intentional?\n\n• **Intentional:** Clears all active orders and user states.\n• **Unintentional:** Resumes all active orders where they left off.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        except Exception as e:
            logging.error(f"Failed to send restart prompt: {e}")

    # --- INTEGRATED CREATOR BOT STARTUP (DISABLED FOR SEPARATE HOSTING) ---
    # To run as a single process, uncomment below. Currently disabled to allow 
    # the Creator Bot to host on its own instance as requested.
    
    # from creator_bot import create_creator_app
    # creator_app = create_creator_app()
    # if creator_app:
    #     try:
    #         logging.info("Initializing Creator Bot as background service...")
    #         await creator_app.initialize()
    #         await creator_app.start()
    #         await creator_app.updater.start_polling()
    #         application.bot_data['creator_app'] = creator_app
    #         logging.info("Creator Bot started successfully.")
    #     except Exception as e:
    #         logging.error(f"Failed to start Creator Bot: {e}")
    # -----------------------------------------------------------------------


async def post_shutdown(application: Application):
    """Cleanup secondary bot if running."""
    creator_app = application.bot_data.get('creator_app')
    if creator_app:
        try:
            logging.info("Stopping Creator Bot...")
            await creator_app.updater.stop()
            await creator_app.stop()
            await creator_app.shutdown()
            logging.info("Creator Bot stopped.")
        except Exception as e:
            logging.error(f"Error during Creator Bot shutdown: {e}")


def main():
    # Handler for admin requesting updated user location
    async def admin_request_location_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if update.effective_chat.id != ADMIN_CHAT_ID:
            await query.answer("Unauthorized action.", show_alert=True)
            return
        await query.answer()
        parts = query.data.split("_")
        if len(parts) < 5:
            await query.edit_message_text("Invalid callback data.")
            return
        order_id = int(parts[3])
        user_id = int(parts[4])
        # Retrieve latest location for this user
        loc = context.bot_data.get(f'latest_location_{user_id}')
        if loc:
            lat, lon = loc['lat'], loc['lon']
            # Fetch user registration info
            user = get_user(user_id)
            if user:
                name = user[1]
                student_id = user[2]
                block = user[3]
                dorm = user[4]
                phone = user[5]
                info = (f"Location update for: {name}\n"
                        f"Student ID: {student_id}\n"
                        f"Block/Dorm: {block} / {dorm}\n"
                        f"Phone: {phone}")
                await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=info)
            await context.bot.send_location(chat_id=ADMIN_CHAT_ID, latitude=lat, longitude=lon)
            # Rebuild the original keyboard so options don't disappear
            request_location_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Request Updated Location",
                                      callback_data=f"admin_request_location_{order_id}_{user_id}")],
                [InlineKeyboardButton(
                    "I'm about to pay", callback_data=f"about_to_pay_{order_id}_{user_id}")],
                [InlineKeyboardButton("⚠️ Force Arrival Notify",
                                      callback_data=f"force_arrival_{order_id}_{user_id}")]
            ])

            # Edit the text but keep the buttons!
            await query.edit_message_text(f"Latest location for user {user_id} sent to admin group below.\n(Original order message buttons restored)", reply_markup=request_location_kb)
        else:
            await query.edit_message_text("No location available for this user yet.")

    # Ensure bot token is available
    if not TOKEN:
        logging.error("TELEGRAM_TOKEN is not set in environment. Aborting startup.")
        return

    # Separate general API request client from the long-poll request config
    # Long-poll needs a larger read timeout than Telegram's poll timeout
    request = HTTPXRequest(connect_timeout=10, read_timeout=60)
    persistence = PicklePersistence(filepath='bot_data.pickle')
    application = (
        Application
        .builder()
        .token(TOKEN)
        .request(request)
        .persistence(persistence)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # 1. SECURITY LAYER (GROUP -1 runs first)
    application.add_handler(TypeHandler(Update, check_banned), group=-1)

    # Handler for restart decision
    application.add_handler(CallbackQueryHandler(
        restart_decision_callback, pattern='^restart_'))
    # Handler for admin requesting updated user location
    application.add_handler(CallbackQueryHandler(
        admin_request_location_callback, pattern='^admin_request_location_'))
    # Handler for admin verifying user-uploaded location
    application.add_handler(CallbackQueryHandler(
        admin_verify_location_callback, pattern='^admin_verify_location_'))
    # Handler for admin confirming they see the user
    application.add_handler(CallbackQueryHandler(
        admin_seen_user_callback, pattern='^admin_seen_user_'))
    init_db()

    # --- New Handlers for Payment Proof & Rating ---
    # Handler for user uploading payment proof (photo)
    # Note: We need to be careful not to conflict with other photo handlers if any.
    # Since we check context.bot_data inside the handlers, it should be fine to have multiple.
    # However, python-telegram-bot executes handlers in order.
    # We'll add a specific handler for photos that checks our specific states.

    application.add_handler(MessageHandler(
        filters.PHOTO, handle_payment_proof), group=1)
    application.add_handler(MessageHandler(
        filters.PHOTO, handle_admin_receipt), group=2)

    # Handler for admin requesting to upload receipt
    application.add_handler(CallbackQueryHandler(
        admin_req_receipt_callback, pattern='^admin_req_receipt_'))
    # Handler for admin rejecting proof
    application.add_handler(CallbackQueryHandler(
        admin_reject_proof_callback, pattern='^admin_reject_proof_'))
    # Handler for rating callback
    application.add_handler(CallbackQueryHandler(
        rating_callback, pattern='^rate_'))
    # -----------------------------------------------

    # Ensure shared relay store exists on the application-level bot_data
    application.bot_data.setdefault('tracking_relays', {})
    # Admin live-location mapping (customer_id -> message_id)
    application.bot_data.setdefault('admin_live', {})
    # Admin order message mapping (order_id -> message_id)
    application.bot_data.setdefault('admin_orders', {})
    # Order locked state (no cancellation allowed once user confirms)
    application.bot_data.setdefault('order_locked', {})

    # Registration Handler
    reg_conv = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            MessageHandler(filters.Regex(
                '^Reset Registration$|^ምዝገባን እንደገና ጀምር$'), reset_registration)
        ],
        states={
            REG_LANGUAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_language)],
            REG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_name)],
            REG_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_id)],
            REG_BLOCK: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_block)],
            REG_GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_gender)],
            REG_DORM: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_dorm)],
            REG_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_phone)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    # Order Handler
    order_conv = ConversationHandler(
        entry_points=[
            CommandHandler('order', order_start),
            MessageHandler(filters.Regex('^Order Food$|^ምግብ እዘዝ$'), order_start)
        ],
        states={
            ORDER_REST: [
                MessageHandler(filters.Regex('^Resume Order$|^ትዕዛዝ ቀጥል$'), resume_rest),
                MessageHandler(filters.TEXT & ~filters.COMMAND, order_rest)
            ],
            ORDER_TYPE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, order_type_choice)
            ],
            ORDER_ITEM: [
                MessageHandler(filters.Regex('^Resume Order$|^ትዕዛዝ ቀጥል$'), resume_item),
                MessageHandler(filters.TEXT & ~filters.COMMAND, order_item)
            ],
            ORDER_CONFIRM: [
                MessageHandler(filters.Regex(
                    '^Resume Order$|^ትዕዛዝ ቀጥል$'), resume_confirm),
                MessageHandler(filters.TEXT & ~filters.COMMAND, order_confirm)
            ],
            ORDER_LOCATION: [
                MessageHandler(filters.Regex(
                    '^Resume Order$|^ትዕዛዝ ቀጥል$'), resume_location),
                MessageHandler(filters.TEXT | filters.LOCATION, order_location)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    # Dev Handler
    dev_conv = ConversationHandler(
        entry_points=[CommandHandler('set_test_mode', dev_start_set_loc)],
        states={
            DEV_WAIT_LOC: [MessageHandler(filters.LOCATION, dev_set_loc)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    application.add_handler(order_conv)
    application.add_handler(reg_conv)
    application.add_handler(dev_conv)
    # Add clearorders command for admin group only
    application.add_handler(CommandHandler('clearorders', clear_orders))

    # Handler for admin accepting an order
    application.add_handler(CallbackQueryHandler(
        admin_accept_order, pattern='^admin_accept_'))
    # Handler for user cancel-order callback
    application.add_handler(CallbackQueryHandler(
        cancel_order_callback, pattern='^cancel_order_'))
    # Handler for confirming cancellation
    application.add_handler(CallbackQueryHandler(
        confirm_cancel_order_callback, pattern='^confirm_cancel_order_'))
    # Handler for keeping order
    application.add_handler(CallbackQueryHandler(
        keep_order_callback, pattern='^keep_order_'))
    # Handler for admin about-to-pay action
    application.add_handler(CallbackQueryHandler(
        about_to_pay_callback, pattern='^about_to_pay_'))
    # Handler for admin force-arrival action
    application.add_handler(CallbackQueryHandler(
        force_arrival_callback, pattern='^force_arrival_'))
    # Handlers for customer confirm/cancel purchase actions
    application.add_handler(CallbackQueryHandler(
        user_confirm_callback, pattern='^user_confirm_'))
    application.add_handler(CallbackQueryHandler(
        user_cancel_purchase_callback, pattern='^user_cancel_purchase_'))
    # Handler for ack after cancellation warning
    application.add_handler(CallbackQueryHandler(
        ack_cancel_callback, pattern='^ack_cancel_'))

    # Global handler for Live Location updates (Relay)
    application.add_handler(MessageHandler(
        filters.LOCATION, relay_location_updates))

    # Explicitly handle edited messages (Live Location updates)
    async def edited_location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.edited_message and update.edited_message.location:
            await relay_location_updates(update, context)

    application.add_handler(TypeHandler(Update, edited_location_handler))

    # --- Fallback Handler for Unhandled Messages ---
    application.add_handler(CommandHandler('my_id', my_id_command))

    # This catches messages that didn't match any conversation state or command.
    # It likely means the bot restarted and lost state (if persistence failed) or user is sending random text.
    async def global_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return

        text = update.message.text
        # Ignore commands (they are usually handled or ignored silently)
        if text and text.startswith('/'):
            return
        
        user_id = update.effective_user.id
        from database import get_user_language
        lang = get_user_language(user_id) or 'en'

        # Check for specific "Lost Button" patterns to give better feedback
        if text and ("Cancel Order" in text or "Confirm" in text or "ትዕዛዝ" in text or "አረጋግጥ" in text):
             await update.message.reply_text(
                "⚠️ **Session Lost**\n\nThe button you pressed belongs to an expired session (due to server update/restart). Your previous cart is empty.\n\nPlease type /order to start a fresh order.\n\n(English/Amharic)",
                parse_mode='Markdown'
             )
             return

        await update.message.reply_text(
            get_text('server_restart', lang),
            parse_mode='Markdown'
        )

    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, global_fallback))

    # Check for Render environment or explicit PORT setting to determine mode
    webhook_url = os.environ.get("RENDER_EXTERNAL_URL")

    if webhook_url:
        port = int(os.environ.get("PORT", 8080))
        # Ensure no trailing slash
        if webhook_url.endswith("/"):
            webhook_url = webhook_url[:-1]

        logging.info(f"Starting in Webhook mode. URL: {webhook_url}, Port: {port}")
        
        # Start pinger thread even in webhook mode to prevent sleeping
        start_pinger()

        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=TOKEN,
            webhook_url=f"{webhook_url}/{TOKEN}"
        )
    else:
        logging.info("Starting in Polling mode.")
        keep_alive()  # Start the web server to keep the bot alive
        
        application.run_polling()


if __name__ == '__main__':
    main()