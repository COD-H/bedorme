# BeDorme Food Delivery Bot

## Overview

BeDorme is a Telegram bot designed to facilitate food delivery for university students living in dorms. It handles the entire process from user registration (Student ID, Block, Dorm) to ordering food from local campus restaurants, tracking delivery locations, and managing orders.

The bot supports **English** and **Amharic** languages.

## Key Features

### 👤 User Registration

- **Profile Management**: Collects Full Name, Student ID, Block, Dorm Number, and Phone Number.
- **Validation**: Ensures valid Student ID formats (e.g., `UGR/1234/12`) and alphabetic names (supporting both English and Amharic characters).
- **Navigation**: Users can step back and correct information during registration using "Back" / "ተመለስ" buttons.

### 🍔 Food Ordering

- **Restaurant Browser**: Dynamic listing of available restaurants (Zebra, Fele, Lucy, etc.).
- **Interactive Menus**: Browse items and prices updated dynamically from the system.
- **Cart Management**: Add multiple items, review order summaries, and cancel specific items.
- **Flexible Location**: Deliver to the registered Dorm or a specific Live Location.

### 🔧 Admin & System

- **Location Verification**: Integration for admins to verify if a user is within delivery range.
- **Dual Database Support**: seamless switching between SQLite (local development) and PostgreSQL (production).

## Technical Improvements & Bug Fixes (Jan 2026)

We have recently performed a comprehensive audit and maintenance session to improve stability and localization.

### 1. Amharic Localization & Navigation

- **Problem**: The "Back" button in the registration flow was hardcoded to check for the English word "Back", causing the bot to get stuck when users clicked the Amharic equivalent "ተመለስ".
- **Solution**: Updated `reg_block`, `reg_dorm`, and `reg_gender` states to handle both "Back" and "ተመለስ" inputs.
- **Enhancement**: Context-aware button labels now correctly display based on the user's selected language.

### 2. Codebase Refactoring

- **Problem**: Code duplication was found in the registration handlers (`reg_block`, `reg_dorm`, etc. were defined twice), leading to conflicting logic and debugging difficulties.
- **Solution**: Removed duplicate function definitions and consolidated logic into single, robust asynchronous handlers.

### 3. Input Validation Hardening

- **Name Input**: Previously rejected valid Amharic names because the regex allowed only `A-Z`. Now accepts Unicode alphabetic characters.
- **Restaurant Selection**: Fixed a typo in hardcoded lists (e.g., "Fle" instead of "Fele") which caused "Invalid Input" errors. The bot now dynamically generates buttons directly from the `MENUS` dictionary to ensure consistency.
- **Student ID**: Improved parsing to better handle formatted strings.

### 4. Stability Fixes

- **"Done Ordering" Crash**: Fixed a logic error where the "I'm Done Ordering" button triggered a crash due to redundant state handling.
- **Missing Features**: Added the "Order Food" button immediately after registration completion for a smoother user experience.

## Setup and Installation

### Dependencies

Install the required packages:

```bash
pip install -r requirements.txt
```

### Configuration

1. Create a `.env` file with your credentials:
   ```
   TOKEN=your_telegram_bot_token
   ADMIN_CHAT_ID=your_admin_id
   # Optional: DATABASE_URL for PostgreSQL
   ```

### Running the Bot

```bash
python bedorme.py
```

## Structure

- `bedorme.py`: Main bot logic and conversation handlers.
- `menus.py`: Dictionary containing restaurant names and menu items.
- `translations.py`: Localization strings for English and Amharic.
- `database.py`: Database abstraction layer (SQLite/PostgreSQL).
