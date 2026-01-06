# if the server (backend) restarts or closes with an incomplite orders then on the next start up i want it to go though the admins channel and find incomplite orders and send a notification saying id #### delivery wasnt complite would u like to re-order this order 1.if admin clicks yes (there is a yes no button) then send the admins channel a message of the full info of the order and tell them to make sure if the order is complite 
#  also i have seen if somone clicks /order it automatically goes in to the order catagory fix that 
# also need to edit the /clearorders button more prosisly 
# fix the location problem it needs work
# fix, the bot dosent collect info from the admin channel ... info like the admin location




#i need to add an amharic version an ask user what language user prefers

# on the admin side when orders pile up its hard to know wich orders are incomplite because the bot keeps updating the maps and the order gets barried under a lot of location updates

# right after the order is complite i want the bot to delete the prompted messages from the user and have a clear page

# user should be able to order multiple orders at once 

# Add the owners account 1000688588972 for her and 1000466307371 for kal

# the /order in the middle of the text is comfuzing ppl and i want ppl to know /order is a link like saying "click the /order in this text"

## Code Quality & Bugs to Fix
- [ ] **Redundant Code**: `database_utils.py` does not contain the `sqlite3` import and is redundant because `database.py` already implements its functions. (Status: Deleted `database_utils.py`)
- [ ] **Logging**: Use of `print()` instead of `logging` prevents proper monitoring in production.
- [ ] **Error Swallowing**: Broad `try...except Exception: pass` blocks hide critical bugs. Need specific exception handling.
- [ ] **Database Paths**: `sqlite3.connect('bedorme.db')` uses a relative path, which is fragile. Should use `os.path.join(os.path.dirname(__file__), 'bedorme.db')`.
- [ ] **Database Concurrency**: Default SQLite `timeout` is low (5s). High traffic might cause locking errors. Increase timeout or implement retry logic.
- [ ] **Data Types**: Prices are stored as `REAL` (float), leading to potential rounding errors.
- [ ] **Hardcoded Config**: Values like `ALLOWED_RADIUS` spread across files.