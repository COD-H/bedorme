
TRANSLATIONS = {
    'en': {
        'choose_lang': "Please choose your language:\nእባክዎ ቋንቋ ይምረጡ:",
        'welcome_reg': "Welcome to BeDorme Food Delivery! Let's get you registered.\n \nPlease enter your Full Name (use the name on your ID):",
        'welcome_back': "Welcome back, {name}!\nYou are already registered and logged in.",
        'order_food': "Order Food",
        'reset_reg': "Reset Registration",
        'resume_rest': "Resuming... Choose a restaurant:",
        'resume_menu': "Resuming... Menu for {restaurant}:\nSelect an item:",
        'resume_confirm': "Resuming... Add more or finish ordering.",
        'confirm_summary': "You are about to confirm the following orders:\n\n",
        'total': "\nTotal: {total} ETB",
        'remove_order': "\nIf you want to remove an order, tap its cancel button below.",
        'done_ordering': "I'm Done Ordering",
        'add_more': "Add More Orders",
        'cancel': "Cancel",
        'confirm': "Confirm",
        'cancel_order_btn': "Cancel Order {i}",
        'reg_reset_msg': "🔄 **Registration Reset**\n\nLet's start over. Please enter your Full Name (use the name on your ID):"
    },
    'am': {
        'choose_lang': "Please choose your language:\nእባክዎ ቋንቋ ይምረጡ:",
        'welcome_reg': "ወደ BeDorme ምግብ አቅርቦት እንኳን በደህና መጡ! ምዝገባ እንጀምር።\n \nእባክዎ ሙሉ ስምዎን ያስገቡ (መታወቂያዎ ላይ እንዳለው):",
        'welcome_back': "እንኳን ደህና መጡ {name}!\nአስቀድመው ተመዝግበዋል እና ገብተዋል።",
        'order_food': "ምግብ እዘዝ",
        'reset_reg': "ምዝገባን እንደገና ጀምር",
        'resume_rest': "በመቀጠል ላይ... ምግብ ቤት ይምረጡ:",
        'resume_menu': "በመቀጠል ላይ... የ {restaurant} ምናሌ:\nምግብ ይምረጡ:",
        'resume_confirm': "በመቀጠል ላይ... ተጨማሪ ይዘዙ ወይም ማዘዝን ይጨርሱ።",
        'confirm_summary': "የሚከተሉትን ትዕዛዞች ሊያረጋግጡ ነው።:\n\n",
        'total': "\nጠቅላላ: {total} ብር",
        'remove_order': "\nትዕዛዝ መሰረዝ ከፈለጉ፣ ከታች ያለውን የመሰረዣ ቁልፍ ይጫኑ።",
        'done_ordering': "አልቀዋል",
        'add_more': "ተጨማሪ እዘዝ",
        'cancel': "ሰርዝ",
        'confirm': "አረጋግጥ",
        'cancel_order_btn': "ትዕዛዝ {i}ን ሰርዝ",
        'reg_reset_msg': "🔄 **ምዝገባ እንደገና ተጀምሯል**\n\nከአዲስ እንጀምር። እባክዎ ሙሉ ስምዎን ያስገቡ (መታወቂያዎ ላይ እንዳለው):"
    }
}

def get_text(key, lang='en'):
    return TRANSLATIONS.get(lang, TRANSLATIONS['en']).get(key, key)
