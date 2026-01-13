# Unfinished Tasks & Next Steps

Here is a summary of what was completed and what remains to be done to fully implement the Amharic translation and Menu update.

## Completed
1.  **Menu Update**: `menus.py` has been updated with the new prices and restaurant list (Zebra, Selam, Promy, Edget, Fele, Twins, Lucy).
2.  **Language Selection**: The bot now asks for language preference (English/Amharic) on startup.
3.  **Registration Translation**: The registration flow (Name, ID, Block, Gender, Dorm, Phone) now supports both languages using `translations.py`.
4.  **Ordering Translation**: The core ordering flow (Restaurant selection, Menu item selection, Adding items) supports translations.
5.  **Conversation Filters**: The bot state handlers were updated to recognize Amharic button presses (e.g., "ምግብ እዘዝ").

## Unfinished / Needs Attention

### 1. Resume Location Handler
The `resume_location` function in `bedorme.py` likely still uses English hardcoded strings.
*   **Action**: Update `resume_location` to use `get_text()` for prompts like "Resuming... Where should we deliver?".

### 2. Database Migration & Creation
The code now includes a `language` column in the `users` table logic (`database.py` and `init_db`).
*   **Action**: 
    1.  Run the bot locally (`python bedorme.py`).
    2.  The `init_db()` function will automatically verify and alter the table to add the `language` column if missing.
    3.  This will create/update the `bedorme.db` file which you can then push to the server.

### 3. "My Location" Button Logic
In `order_location`, the logic checks for specific text responses.
*   **Action**: Ensure that when a user clicks "ቦታዬን አጋራ" (Share My Location in Amharic), the bot correctly maps this to the 'My Location' logic. The current code attempts this mapping, but it needs real-world testing to ensure the button text matches the check exactly.

### 4. Admin Interaction
Messages sent to the **Admin** (e.g., "New Order Received", "Payment Proof") are currently in English.
*   **Decision**: Decide if Admin notifications need to be in Amharic as well, or if English is fine for the admin group. Currently, they remain in English.

### 5. Error & Fallback Messages
Some edge-case error messages (e.g., "Invalid input", "Server Restarted") in the `global_fallback` or `dev_conv` handlers might still be hardcoded in English.
*   **Action**: Scan `bedorme.py` for any remaining `"strings"` inside `await update.message.reply_text("...")` calls and replace them with `get_text` calls if strict translation is required.

### 6. Testing
*   **Action**: Test the full flow in Amharic:
    *   Start -> Choose Amharic.
    *   Register -> Verify prompts are Amharic.
    *   Order -> Verify menu buttons and "Add More" / "Done" buttons work in Amharic.
    *   Cancel an item -> Verify "ትዕዛዝ {i}ን ሰርዝ" works.
