# --- Admin Seen User Callback ---

import time
import math
import asyncio
from locations import RESTAURANTS, BLOCKS, ALLOWED_RADIUS
from menus import MENUS
from database import init_db, add_user, create_order, get_user
from database import get_order
from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters, CallbackQueryHandler, PicklePersistence
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.request import HTTPXRequest
from dotenv import load_dotenv
import string
import re
import random
import os
import logging
import sqlite3




async def admin_seen_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback when admin confirms they have seen the user (within 50m)."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 5:
        await query.edit_message_text("Invalid callback data.")
        return
    order_id = int(parts[3])
    user_id = int(parts[4])
    
    # Notify user to start payment process and upload proof
    await context.bot.send_message(
        chat_id=user_id,
        text=(f"Start the payment process for order #{order_id} to the account 1000397137833 CBE account.\n"
              "Only complete transferring after you have verified the package.\n\n"
              "📸 **Please upload a screenshot/photo of the payment proof here.**")
    )
    
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
        [InlineKeyboardButton("Verify & Upload Receipt", callback_data=f"admin_req_receipt_{order_id}_{user_id}")]
    ])
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text="Verify the payment. If received, click below to upload your confirmation receipt.",
        reply_markup=kb
    )
    
    # Clear user waiting state
    del context.bot_data[f'waiting_payment_proof_{user_id}']
    await update.message.reply_text("Payment proof sent! Waiting for admin verification.")


async def admin_req_receipt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin clicked 'Verify & Upload Receipt'."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
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
    from database import get_order
    order = get_order(order_id)
    if not order:
        return
    
    user_id = order[1] # customer_id is at index 1

    photo = msg.photo[-1]
    file_id = photo.file_id
    
    # 1. Forward receipt to user
    try:
        await context.bot.send_message(chat_id=user_id, text=f"✅ Payment Verified! Here is your receipt for Order #{order_id}:")
        await context.bot.send_photo(chat_id=user_id, photo=file_id)
    except Exception as e:
        logger.warning(f"Failed to send receipt to user: {e}")

    # 2. Mark order complete
    try:
        from database import mark_order_complete, get_order, get_user
        mark_order_complete(order_id)
        
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

        caption = (
            f"✅ <b>Order #{order_id} COMPLETED</b>\n"
            f"👤 <b>User:</b> {user_name} (ID: {user_id_display})\n"
            f"📞 <b>Phone:</b> {user_phone}\n"
            f"🏠 <b>Dorm:</b> {user_block} / {user_dorm}\n"
            f"📍 <b>Restaurant:</b> {rest_name}\n"
            f"🍔 <b>Item:</b> {item_name}\n"
            f"💰 <b>Price:</b> {price_display} ETB"
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
            text=(
                "🛑 **Please Stop Sharing Your Live Location**\n\n"
                "To protect your privacy and save battery:\n"
                "1. Tap the 'Stop Sharing Location' bar at the top of this chat.\n"
                "   OR\n"
                "2. Tap the map in the chat and select 'Stop Sharing'."
            ),
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
            row.append(InlineKeyboardButton(str(i), callback_data=f"rate_{order_id}_{i}"))
            if len(row) == 5:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
            
        await context.bot.send_message(
            chat_id=user_id,
            text="How was your delivery experience? Please rate us from 1 (Worst) to 10 (Best):",
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
    
    # Clean up other order data
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
        relays = context.bot_data.get('tracking_relays', {})
        # relays is keyed by admin_id
        for k in list(relays.keys()):
            if relays[k].get('order_id') == order_id: 
                del relays[k]
                logger.info(f"Removed relay for admin {k}")

        # 4. Remove locks
        order_locked = context.bot_data.get('order_locked', {})
        if order_id in order_locked: del order_locked[order_id]
        
    except Exception as e:
        logger.error(f"Error during cleanup for order {order_id}: {e}")


async def rating_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    order_id = int(parts[1])
    rating = int(parts[2])
    
    from database import save_rating
    save_rating(order_id, rating)
    
    await query.edit_message_text(f"Thank you! You rated this order {rating}/10.")


# --- Payment Confirmation Callback (Legacy/Fallback) ---


async def admin_user_paid_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 5:
        await query.edit_message_text("Invalid callback data.")
        return
    order_id = int(parts[4])
    user_id = int(parts[5])

    # Mark order as complete in DB
    try:
        from database import mark_order_complete, get_order, get_user
        mark_order_complete(order_id)
    except Exception:
        pass

    # Notify both user and admin group
    try:
        await context.bot.send_message(chat_id=user_id, text=f"✅ Payment received! Your order #{order_id} is complete. Thank you for using BeDorme.")
        await context.bot.send_message(chat_id=user_id, text="If you shared your live location for this order, please stop sharing it now for your privacy and to save resources. Thank you!")
    except Exception:
        pass
    try:
        await query.edit_message_text(f"Order #{order_id} marked as complete. Payment confirmed.")
    except Exception:
        pass

    # Send completed order info to DB group
    try:
        DB_GROUP_CHAT_ID = -1003306702660
        order = get_order(order_id)
        user = get_user(user_id)
        if order and user:
            order_info = (
                f"Order Complete!\n"
                f"Order ID: {order[0]}\n"
                f"Customer: {user[1]} (ID: {user[0]})\n"
                f"Student ID: {user[2]}\n"
                f"Block/Dorm: {user[3]} / {user[4]}\n"
                f"Phone: {user[5]}\n"
                f"Restaurant: {order[3]}\n"
                f"Item: {order[4]}\n"
                f"Price: {order[5]} ETB\n"
                f"Verification Code: {order[7]}\n"
                f"Status: {order[6]}\n"
                f"Delivery Location: {order[11]}, {order[12]}\n"
                f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}"
            )
            await context.bot.send_message(chat_id=DB_GROUP_CHAT_ID, text=order_info)
    except Exception as e:
        logger.warning(f"Failed to send completed order info to DB group: {e}")

    # Clean up order activity (remove from bot_data)
    try:
        admin_orders = context.bot_data.get('admin_orders', {})
        if order_id in admin_orders:
            del admin_orders[order_id]
        order_locked = context.bot_data.get('order_locked', {})
        if order_id in order_locked:
            del order_locked[order_id]
        user_cancel_msgs = context.bot_data.get('user_cancel_msgs', {})
        if order_id in user_cancel_msgs:
            del user_cancel_msgs[order_id]
        # Remove live location relay if any
        relays = context.bot_data.get('tracking_relays', {})
        for k in list(relays.keys()):
            if relays[k].get('order_id') == order_id:
                del relays[k]
        admin_live = context.bot_data.get('admin_live', {})
        for k in list(admin_live.keys()):
            if admin_live[k].get('order_id') == order_id:
                del admin_live[k]
    except Exception:
        pass

# 1. Standard setup: Show INFO for your own code
#logging only shows WARNING and above by default, so we set it to INFO
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
REG_NAME, REG_ID, REG_BLOCK, REG_GENDER, REG_DORM, REG_PHONE = range(6)
ORDER_REST, ORDER_ITEM, ORDER_CONFIRM, ORDER_LOCATION = range(5, 9)
PICKUP_LOCATION, PICKUP_PROOF, DELIVERY_LOCATION, DELIVERY_PROOF, DELIVERY_CODE = range(
    9, 14)
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
    await update.message.reply_text(
        "Welcome to BeDorme Food Delivery! Let's get you registered.\n \n"
        "Please enter your Full Name (use the name on your ID):"
    )
    return REG_NAME

async def reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()

    # Must contain only alphabetic characters and spaces
    if not re.match(r'^[A-Za-z ]+$', name):
        await update.message.reply_text(
            "Invalid input: all characters in the full name must be alphabetic letters and spaces.\n"
            "Please enter your Full Name (use the name on your ID):"
        )
        return REG_NAME

    # Split into parts and require at least two parts
    parts = [p for p in name.split() if p]
    if len(parts) < 2:
        await update.message.reply_text(
            "You also need to input your father name — include a space between names.\n"
            "Please enter your Full Name (FirstName FatherName):"
        )
        return REG_NAME

    # Each of the first two name parts must be at least 3 alphabetic letters
    if len(parts[0]) < 3 or len(parts[0]) > 12 or len(parts[1]) < 3 or len(parts[1]) > 12:
        await update.message.reply_text(
            "Each of the first and second name parts must be at least 3 at most 12 alphabetic letters.\n"
            "Please enter your Full Name (FirstName FatherName) <-- in this format:"
        )
        return REG_NAME

    context.user_data['name'] = name
    # Prompt for student ID and allow going back to name if needed
    await update.message.reply_text(
        "Great! Now enter your Student ID:",
        reply_markup=ReplyKeyboardMarkup(
            [['Back']], one_time_keyboard=True, resize_keyboard=True)
    )
    return REG_ID
async def reg_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sid = update.message.text.strip()

    # --- NEW PARAMETER CHECK: BLOCK COMMANDS ---
    # We use a tuple ('/', '\\') to catch both forward and backslashes
    if sid.startswith(('/', '\\')):
        await update.message.reply_text(
            "❌ **Invalid Input**\n\n"
            "Please follow the registration step to order! Use /start to begin.\n"
            "Now, please enter your **Student ID** to continue:",
            parse_mode='Markdown'
        )
        return REG_ID


    # --- YOUR ORIGINAL STRUCTURE START ---
    # Handle 'Back' to edit the name
    if sid.lower() == 'back':
        await update.message.reply_text(
            "Okay — please re-enter your Full Name (use the name on your ID):",
            reply_markup=ReplyKeyboardMarkup(
                [['Back']], one_time_keyboard=True, resize_keyboard=True)
        )
        return REG_NAME

    # Accept formats like: nsr/1234/16  or  EX-123-18
    pattern = r'^(nsr|ex)[/\-_.](\d{3,4})[/\-_.](\d{2})$'
    m = re.match(pattern, sid, flags=re.I)
    if not m:
        await update.message.reply_text(
            "Invalid Student ID format. Use one of:\n"
            "   nsr/1234/16   (or)   EX-123-18\n"
            "Prefix must be 'nsr' or 'ex', middle 3–4 digits, last two digits between 14 and 18.\n"
            "Please enter your Student ID:"
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
    
    keyboard.append(['Back'])

    await update.message.reply_text(
        "Student ID accepted. Please choose your Block (or select a special area):",
        reply_markup=ReplyKeyboardMarkup(
            keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return REG_BLOCK

async def reg_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # If user selected the special NEWYORK area, show a list of NewYork-area blocks
    if text == 'NEWYORK':
        ny_blocks = context.bot_data.get('newyork_blocks')
        if not ny_blocks:
            # filler choices for now (random numbers below 15)
            ny_blocks = [f"Block {random.randint(1, 14)}" for _ in range(6)]
            context.bot_data['newyork_blocks'] = ny_blocks

        kb = [[b] for b in ny_blocks]
        kb.append(['Back'])
        await update.message.reply_text("Select the NewYork block:", reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True))
        return REG_BLOCK

    # If user selected the GC area, ask for gender first
    if text == 'Around GC Building':
        await update.message.reply_text("Please select your Gender:", reply_markup=ReplyKeyboardMarkup([['Male', 'Female']], one_time_keyboard=True, resize_keyboard=True))
        return REG_GENDER

    # Otherwise assume this is the final block selection
    # Handle Back selection: go back to Student ID entry
    if text.lower() == 'back':
        await update.message.reply_text("Please re-enter your Student ID:", reply_markup=ReplyKeyboardMarkup([['Back']], one_time_keyboard=True, resize_keyboard=True))
        return REG_ID

    context.user_data['block'] = text
    await update.message.reply_text(
        "Please input accurate information to avoid delivery issues.\n\n"
        "Enter your Dorm Number:")
    return REG_DORM


async def reg_dorm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() == 'back':
        # go back to block selection
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
        keyboard.append(['Back'])
        await update.message.reply_text("Select your Block:", reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
        return REG_BLOCK

    context.user_data['dorm'] = text
    # Reset attempts here so they always get 5 fresh tries
    context.user_data['phone_attempts'] = 0 
    await update.message.reply_text("Finally, enter your Phone Number (starting with 09, 07, +2519, or +2517):")
    return REG_PHONE


async def reg_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle gender selection for 'Around GC Building' flow and present block choices."""
    gender = update.message.text.strip().lower()
    if gender.lower() == 'back':
        # go back to block selection
        # rebuild block keyboard
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
        keyboard.append(['Back'])
        await update.message.reply_text("Select your Block:", reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
        return REG_BLOCK

    if gender not in ('male', 'female'):
        await update.message.reply_text("Please choose 'Male' or 'Female'.", reply_markup=ReplyKeyboardMarkup([['Male', 'Female'], ['Back']], one_time_keyboard=True, resize_keyboard=True))
        return REG_GENDER

    context.user_data['gender'] = gender.capitalize()
    # Use the explicit GC-area block names provided by the user for both genders
    gc_blocks = [
        "Arctecture/ Civil block",
        "water_block",
        "mechanical_electrical_block",
        "2ND_comp/ 2ND_soft_block",
        "soft / comp GC_block",
        "unassigned",
    ]

    key = 'gc_male_blocks' if gender == 'male' else 'gc_female_blocks'
    # store the same list for both genders so it's available later
    context.bot_data.setdefault(key, gc_blocks)
    blocks = context.bot_data[key]

    kb = [[b] for b in blocks]
    # ensure a single Back row is present
    if ['Back'] not in kb:
        kb.append(['Back'])
    await update.message.reply_text("Select your block around GC Building:", reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True))
    # Next message will be handled by reg_block which will store the chosen block
    return REG_BLOCK


async def reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    # --- 1. HANDLE BACK BUTTON ---
    if text.lower() == 'back':
        await update.message.reply_text("Please re-enter your Dorm Number:", reply_markup=ReplyKeyboardMarkup([['Back']], one_time_keyboard=True, resize_keyboard=True))
        return REG_DORM

    # --- 2. VALIDATION LOGIC ---
    is_valid = False
    error_msg = ""

    # Rule: Starts with 09 or 07 -> Must be exactly 10 digits
    if text.startswith(('09', '07')):
        if text.isdigit() and len(text) == 10:
            is_valid = True
        else:
            error_msg = "❌ Invalid: Numbers starting with 09 or 07 must be exactly 10 digits and contain no symbols."

    # Rule: Starts with +2517 or +2519 -> Must be exactly 13 characters
    elif text.startswith(('+2519', '+2517')):
        if text[1:].isdigit() and len(text) == 13:
            is_valid = True
        else:
            error_msg = "❌ Invalid: Numbers starting with +251 must be exactly 13 characters (e.g., +251912345678)."
    
    else:
        error_msg = "❌ Invalid: Number must start with 09, 07, +2519, or +2517."

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

    # Keeping your database call exactly as it was
    add_user(user_id, user_data['name'], user_data['student_id'],
             user_data['block'], user_data['dorm'], user_data['phone'])

    # Cleanup attempts counter
    if 'phone_attempts' in context.user_data:
        del context.user_data['phone_attempts']

    # --- 5. TRIGGER ORDER PROMPT AUTOMATICALLY ---
    await update.message.reply_text("✅ Registration Complete! u can now place your /order.")
    
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operation cancelled.", reply_markup=ReplyKeyboardRemove())
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
    keyboard = [
        ['Fle', 'Zebra'],
        ['Wesen', 'Selam'],
        ['Webete (Premium)', 'Darek (Premium)']
    ]
    await update.message.reply_text(
        "Choose a restaurant:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return ORDER_REST

async def admin_accept_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback when admin taps 'Order Received' button in the admin group."""
    query = update.callback_query
    await query.answer()

    # callback format: admin_accept_{order_id}_{customer_id}
    parts = query.data.split("_")
    if len(parts) < 3:
        await query.edit_message_text("Invalid callback data.")
        return

    order_id = int(parts[2])
    customer_id = int(parts[3]) if len(parts) > 3 else None

    # Mark order as accepted and update admin message to show it's been accepted
    admin_orders = context.bot_data.setdefault('admin_orders', {})
    admin_entry = admin_orders.get(order_id)
    request_location_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Request Updated Location",
                              callback_data=f"admin_request_location_{order_id}_{customer_id}")],
        [InlineKeyboardButton(
            "I'm about to pay", callback_data=f"about_to_pay_{order_id}_{customer_id}")],
        [InlineKeyboardButton("⚠️ Force Arrival Notify", callback_data=f"force_arrival_{order_id}_{customer_id}")]
    ])
    if admin_entry is None:
        try:
            await query.edit_message_text(f"✅ Order #{order_id} marked as received by admin {query.from_user.first_name}.", reply_markup=request_location_kb)
        except Exception:
            pass
    else:
        admin_entry['accepted'] = True
        admin_entry['admin_id'] = query.from_user.id  # Store the admin ID who accepted the order
        try:
            await query.edit_message_text(f"✅ Order #{order_id} marked as received by admin {query.from_user.first_name}.", reply_markup=request_location_kb)
        except Exception:
            try:
                await query.edit_message_text(f"✅ Order #{order_id} marked as received by admin {query.from_user.first_name}.")
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
            order_info += (f"\nCustomer: {customer[1]} (tg id: {customer[0]})"
                           f"\nStudent ID: {customer[2]}"
                           f"\nBlock/Dorm: {customer[3]} / {customer[4]}"
                           f"\nPhone: {customer[5]}")
        if order:
            order_info += (f"\nRestaurant: {order[3]}"
                           f"\nItem: {order[4]}"
                           f"\nPrice: {order[5]} ETB"
                           f"\nVerification Code: {order[7]}")

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
    await query.answer()
    parts = query.data.split("_")
    order_id = int(parts[2])
    user_id = int(parts[3])

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
            [InlineKeyboardButton("Yes", callback_data=f"admin_seen_user_{order_id}_{user_id}")]
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
    choice = update.message.text.replace(" (Premium)", "")
    if choice not in MENUS:
        await update.message.reply_text("Please select a valid restaurant.")
        return ORDER_REST

    context.user_data['restaurant'] = choice
    menu = MENUS[choice]

    # Create menu buttons
    keyboard = []
    for item, price in menu.items():
        keyboard.append([f"{item} - {price} ETB"])

    await update.message.reply_text(
        f"Menu for {choice}:\nSelect an item:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    )
    return ORDER_ITEM

async def order_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    # --- PARAMETER CHECK: PREVENT CRASH & UNAUTHORIZED COMMANDS ---
    if " - " not in text or text.startswith('/'):
        await update.message.reply_text(
            "⚠️ **Unauthorized Access**\n\n"
            "Finish the process you started! Please select a food item "
            "from the buttons provided.",
            parse_mode='Markdown'
        )
        # Keep user in the current state so they must pick a valid item
        return ORDER_ITEM

    # --- YOUR ORIGINAL STRUCTURE (INTACT) ---
    item_name = text.split(" - ")[0]
    price = float(text.split(" - ")[1].replace(" ETB", ""))

    context.user_data['item'] = item_name
    context.user_data['price'] = price

    await update.message.reply_text(
        f"Confirm Order:\nRestaurant: {context.user_data['restaurant']}\nItem: {item_name}\nPrice: {price} ETB\n\nTap 'Confirm' to proceed to location selection.",
        reply_markup=ReplyKeyboardMarkup(
            [['Confirm'], ['Cancel']], one_time_keyboard=True, resize_keyboard=True)
    )
    return ORDER_CONFIRM

async def order_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # 1. VALID: User clicks 'Confirm' -> Moves to Location Selection
    if text == 'Confirm':
        await update.message.reply_text(
            "Where should we deliver?\n\n"
            "1. **Dorm**: Uses your registered Block/Dorm.\n"
            "2. **My Location**: Share your current location pin.",
            reply_markup=ReplyKeyboardMarkup(
                [['Dorm', 'My Location']], one_time_keyboard=True, resize_keyboard=True),
            parse_mode='Markdown'
        )
        # This includes the transition you asked for
        return ORDER_LOCATION

    # 2. VALID: User clicks 'Cancel' -> Ends the conversation
    elif text == 'Cancel':
        await update.message.reply_text("Order cancelled.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    # 3. INVALID PARAMETER: User types anything else
    else:
        await update.message.reply_text(
            "⚠️ Invalid input. Please use the buttons below to **Confirm** or **Cancel** your order.",
            reply_markup=ReplyKeyboardMarkup(
                [['Confirm', 'Cancel']], one_time_keyboard=True, resize_keyboard=True),
            parse_mode='Markdown'
        )
        # This keeps the user in the same state to try again
        return ORDER_CONFIRM


async def order_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return ORDER_LOCATION

    text = message.text
    lat, lon = None, None

    if text == 'Dorm':
        # Look up user block
        user = get_user(update.effective_user.id)
        block = user[3]  # block column
        if block in BLOCKS:
            lat, lon = BLOCKS[block]
        else:
            # Fallback if block not in map, use Block 1 as default or handle error
            lat, lon = BLOCKS.get("Block 1")

    elif text == 'My Location':
        await message.reply_text(
            "To share your live location:\n"
            "1. Tap the paperclip icon 📎 (or +).\n"
            "2. Select **Location** 📍.\n"
            "3. Select **'Share My Live Location'**.\n"
            "4. Choose **'Until I turn it off'**.\n\n"
            "This helps the deliverer find you exactly where you are!",
            parse_mode='Markdown'
        )
        return ORDER_LOCATION  # Stay in state until location received

    elif message.location:
        lat = message.location.latitude
        lon = message.location.longitude
        # Ask admin group to verify location
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "Accept", callback_data=f"admin_verify_location_yes_{update.effective_user.id}_{lat}_{lon}"),
                InlineKeyboardButton(
                    "Reject", callback_data=f"admin_verify_location_no_{update.effective_user.id}_{lat}_{lon}")
            ]
        ])
        await update.message.reply_text("Location uploaded! Waiting for admin verification...")
        await context.bot.send_location(
            chat_id=ADMIN_CHAT_ID,
            latitude=lat,
            longitude=lon
        )
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"User {update.effective_user.full_name} (ID: {update.effective_user.id}) uploaded a location for their order. Accept this location?",
            reply_markup=kb
        )
        # Store location in user_data for later
        context.user_data['pending_location'] = (lat, lon)
        
        # Store pending order details in bot_data so we can access it in the callback
        # The callback comes from the admin, so we can't access the user's context.user_data there easily.
        context.bot_data[f'pending_order_{update.effective_user.id}'] = {
            'restaurant': context.user_data.get('restaurant'),
            'item': context.user_data.get('item'),
            'price': context.user_data.get('price')
        }
        
        return ORDER_LOCATION
# --- Admin verifies user-uploaded location ---


async def admin_verify_location_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 6:
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

            order_id = create_order(
                user_id,
                pending_order['restaurant'],
                pending_order['item'],
                pending_order['price'],
                code,
                lat,
                lon
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
                        admin_live = context.bot_data.setdefault('admin_live', {})
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

            await context.bot.send_message(chat_id=user_id, text=f"Order Placed! Admin will review your order.\n\nIMPORTANT: Your verification code is *{code}*. Keep it safe.", parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
            
            # Send an inline Cancel Order button that prompts the user to re-enter their name if clicked
            try:
                kb = InlineKeyboardMarkup([[InlineKeyboardButton(
                    "Cancel Order", callback_data=f"cancel_order_{order_id}")]])
                sent_cancel = await context.bot.send_message(chat_id=user_id, text="If you wish to cancel your order, press below:", reply_markup=kb)
                # store user's cancel-button message id so we can remove it if admin proceeds to purchase
                user_cancel_msgs = context.bot_data.setdefault('user_cancel_msgs', {})
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
        print(f"DEBUG: relay_location_updates called but no location found. Update: {update.to_dict()}")
        return

    chat_id = msg.chat_id
    sender_id = msg.from_user.id
    lat = msg.location.latitude
    lon = msg.location.longitude
    print(f"DEBUG: Location update from {sender_id} in chat {chat_id}: {lat}, {lon}")
    # Store latest user location in bot_data for on-demand admin requests
    context.bot_data[f'latest_location_{sender_id}'] = {
        'lat': lat, 'lon': lon, 'timestamp': time.time()}

    # --- Rate limiting logic ---
    now = time.time()
    key = f"{chat_id}:{sender_id}"
    last = last_location_update.get(key, 0)
    if now - last < LOCATION_UPDATE_INTERVAL:
        print(f"DEBUG: Rate limit hit for {key}, skipping update.")
        return
    last_location_update[key] = now

    # --- New: If location is sent in the admin group, relay to user ---
    if chat_id == ADMIN_CHAT_ID:
        # Try to find the latest accepted order for this admin
        admin_orders = context.bot_data.get('admin_orders', {})
        # Find the most recent order accepted by this admin
        for order_id, entry in admin_orders.items():
            # Only relay if order is still active and not completed/cancelled
            if not entry.get('active', True):
                continue
            
            # Check if this order was accepted by the current sender (admin)
            # If admin_id is not set (legacy orders), we might default to sender_id, but it's safer to require it.
            # However, for now, let's use get('admin_id', sender_id) to be backward compatible if needed,
            # but since we just added the fix to store admin_id, it should work for new orders.
            assigned_admin = entry.get('admin_id')
            
            if entry.get('accepted') and (assigned_admin == sender_id or assigned_admin is None):
                # Get order info
                from database import get_order, get_user
                order = get_order(order_id)
                if order:
                    user_id = order[1]  # customer_id
                    # Relay location to user
                    relay_key = f"relay_{user_id}_{order_id}"
                    last_msg_id = context.bot_data.get(relay_key)
                    
                    sent = None
                    if last_msg_id:
                        try:
                            await context.bot.edit_message_live_location(
                                chat_id=user_id,
                                message_id=last_msg_id,
                                latitude=lat,
                                longitude=lon
                            )
                        except Exception as e:
                            # If edit fails (e.g. message deleted or live period expired), send new one
                            print(f"DEBUG: Failed to edit live location for user {user_id}: {e}")
                            last_msg_id = None # Force new send
                    
                    if not last_msg_id:
                        try:
                            sent = await context.bot.send_location(
                                chat_id=user_id,
                                latitude=lat,
                                longitude=lon,
                                live_period=3600
                            )
                            # Store the new message id
                            context.bot_data[relay_key] = sent.message_id
                        except Exception as e:
                            logger.warning(f"Failed to send live location to user: {e}")

                    # Now check if within 50m
                    user = get_user(user_id)
                    user_lat = order[11]  # delivery_lat
                    user_lon = order[12]  # delivery_lon
                    if user_lat is not None and user_lon is not None:
                        distance = haversine(lat, lon, user_lat, user_lon)
                        # Increased radius to 150m for better detection
                        if distance < 150:
                            notified_key = f"arrived_{order_id}"
                            if not context.bot_data.get(notified_key):
                                await context.bot.send_message(
                                    chat_id=user_id,
                                    text="Your food has arrived! You will shortly receive a call from our agents."
                                )
                                phone = user[5] if user and len(
                                    user) > 5 else "(unknown)"
                                from telegram import InlineKeyboardMarkup, InlineKeyboardButton
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
                break
    query = update.callback_query
    if query:
        await query.answer()
        parts = query.data.split("_")
        if len(parts) < 5:
            await query.edit_message_text("Invalid callback data.")
            return
        order_id = int(parts[3])
        user_id = int(parts[4])
        # Notify user to start payment process
        await context.bot.send_message(
            chat_id=user_id,
            text=f"Start the payment process for order #{order_id} to the account 1000397137833 CBE account and only complete transferring after you have verified the package."
        )
        try:
            await query.edit_message_text("Confirmed: You have seen the receiver. User has been notified to start payment.")
        except Exception:
            pass

    # Check if we have a relay set up for this user
    relays = context.bot_data.get('tracking_relays', {})
    print(f"DEBUG: Current relays keys: {list(relays.keys())}")

    if sender_id in relays:
        target = relays[sender_id]
        try:
            print(f"DEBUG: Relaying to {target.get('chat_id')}")
            # If target has a message_id we can edit the live location, otherwise send a new location
            if target.get('message_id'):
                await context.bot.edit_message_live_location(
                    chat_id=target['chat_id'],
                    message_id=target['message_id'],
                    latitude=lat,
                    longitude=lon
                )
            else:
                sent = await context.bot.send_location(
                    chat_id=target['chat_id'],
                    latitude=lat,
                    longitude=lon,
                    live_period=3600
                )
                # store the message_id so subsequent updates can edit instead of sending new messages
                try:
                    target['message_id'] = sent.message_id
                except Exception:
                    pass

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
    if len(parts) >= 2:
        try:
            order_id = int(parts[1])
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
        await context.bot.send_message(chat_id=user_id, text=(
            "Order cancellation selected. Note: cancellation is only possible if the item has NOT yet been purchased.\n"
            "If you haven't paid / confirmed purchase, the order may be cancelled.\n"
            "Please enter your Full Name (use the name on your ID) to continue:"))
    except Exception:
        pass


async def about_to_pay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin clicked 'I'm about to pay' — ask customer to confirm purchase."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 3:
        await query.edit_message_text("Invalid callback data.")
        return
    order_id = int(parts[2])
    customer_id = int(parts[3]) if len(parts) > 3 else None

    # find admin order entry for later edits and check accepted state
    admin_orders = context.bot_data.get('admin_orders', {})
    admin_entry = admin_orders.get(order_id)
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
        await query.edit_message_text("🔔 Confirmation request sent to customer.")
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

    # Update admin message to show green light
    try:
        if admin_msg_id:
            await context.bot.edit_message_text(chat_id=ADMIN_CHAT_ID, message_id=admin_msg_id, text=f"🟢 Order #{order_id}: Customer CONFIRMED purchase.")
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

    # Update admin message to show red light
    try:
        if admin_msg_id:
            await context.bot.edit_message_text(chat_id=ADMIN_CHAT_ID, message_id=admin_msg_id, text=f"🔴 Order #{order_id}: Customer CANCELLED purchase request.")
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
    # Prompt user to re-enter full name (loop back)
    try:
        await context.bot.send_message(chat_id=user_id, text="Acknowledged. Please enter your Full Name (use the name on your ID):")
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
    await query.answer()
    data = query.data
    
    if data == "restart_reset":
        # Clear all data
        context.application.user_data.clear()
        context.application.chat_data.clear()
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


async def post_init(application: Application):
    # Check if we have resumed state (bot_data is not empty)
    # We check specific keys that indicate active state
    if application.bot_data.get('admin_orders') or application.bot_data.get('admin_live'):
        # Send message to admin
        keyboard = [
            [InlineKeyboardButton("Intentional (Reset Data)", callback_data="restart_reset")],
            [InlineKeyboardButton("Unintentional (Resume)", callback_data="restart_resume")]
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


def main():
    # Handler for admin requesting updated user location
    async def admin_request_location_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
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
            await query.edit_message_text(f"Latest location for user {user_id} sent to admin group.")
        else:
            await query.edit_message_text("No location available for this user yet.")

    request = HTTPXRequest(connect_timeout=60, read_timeout=60)
    persistence = PicklePersistence(filepath='bot_data.pickle')
    application = Application.builder().token(TOKEN).request(request).persistence(persistence).post_init(post_init).build()
    
    # Handler for restart decision
    application.add_handler(CallbackQueryHandler(restart_decision_callback, pattern='^restart_'))
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
    # Handler for admin confirming user payment
    application.add_handler(CallbackQueryHandler(
        admin_user_paid_callback, pattern='^admin_user_paid_yes_'))
    
    # --- New Handlers for Payment Proof & Rating ---
    # Handler for user uploading payment proof (photo)
    # Note: We need to be careful not to conflict with other photo handlers if any.
    # Since we check context.bot_data inside the handlers, it should be fine to have multiple.
    # However, python-telegram-bot executes handlers in order.
    # We'll add a specific handler for photos that checks our specific states.
    
    application.add_handler(MessageHandler(filters.PHOTO, handle_payment_proof), group=1)
    application.add_handler(MessageHandler(filters.PHOTO, handle_admin_receipt), group=2)
    
    # Handler for admin requesting to upload receipt
    application.add_handler(CallbackQueryHandler(admin_req_receipt_callback, pattern='^admin_req_receipt_'))
    # Handler for rating callback
    application.add_handler(CallbackQueryHandler(rating_callback, pattern='^rate_'))
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
        entry_points=[CommandHandler('start', start)],
        states={
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
        entry_points=[CommandHandler('order', order_start)],
        states={
            ORDER_REST: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_rest)],
            ORDER_ITEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_item)],
            ORDER_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_confirm)],
            ORDER_LOCATION: [MessageHandler(filters.TEXT | filters.LOCATION, order_location)],
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
    # Handler for user cancel-order callback (will prompt re-entry of full name)
    application.add_handler(CallbackQueryHandler(
        cancel_order_callback, pattern='^cancel_order_'))
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

    application.run_polling()


if __name__ == '__main__':
    main()
