import os
from dotenv import load_dotenv
load_dotenv()

SCRATCH_DIR = "/workspace/scratch" if os.path.exists("/workspace/scratch") else os.path.join(os.getcwd(), "scratch")
os.makedirs(SCRATCH_DIR, exist_ok=True)
import sys
import time
import json
import requests
import re
import database
import agent

# Telegram Bot Token supplied via env variables
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
API_URL = f"https://api.telegram.org/bot{TOKEN}"

# Memory cache for active conversations (clears on /new, but database persists!)
chat_sessions = {}

def convert_markdown_to_html(text):
    if not text:
        return text
    # 1. Convert bold markdown **text** to HTML <b>text</b>
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    
    # 2. Convert italic markdown *text* or _text_ to HTML <i>text</i>
    text = re.sub(r'_(.*?)_', r'<i>\1</i>', text)
    
    # 3. Handle bullets: convert lines starting with "* " to bullet points "• "
    lines = []
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped.startswith('* '):
            indent = len(line) - len(line.lstrip())
            line = ' ' * indent + '• ' + stripped[2:]
        lines.append(line)
    text = '\n'.join(lines)
    
    # 4. Remove any remaining raw asterisks that failed to parse to prevent unparsed Markdown leakage
    text = text.replace('**', '').replace('*', '')
    
    return text

def send_message(chat_id, text):
    # Programmatically sanitize text so unparsed markdown asterisks never leak to Telegram HTML parse mode
    sanitized_text = convert_markdown_to_html(text)
    
    payload = {
        "chat_id": chat_id,
        "text": sanitized_text,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(f"{API_URL}/sendMessage", json=payload)
        return r.json()
    except Exception as e:
        print(f"Error sending telegram message: {e}")

def send_document(chat_id, filepath, caption=""):
    try:
        with open(filepath, "rb") as f:
            files = {"document": f}
            data = {"chat_id": chat_id, "caption": caption}
            r = requests.post(f"{API_URL}/sendDocument", data=data, files=files)
            return r.json()
    except Exception as e:
        print(f"Error sending document: {e}")

def handle_start_command(chat_id):
    welcome_text = (
        "<b>Namaste! Welcome to Sri Krishna Kirana Store AI Ops Manager!</b> 🙏\n\n"
        "You can run this entire store in plain language through me. I manage "
        "your inventory, cut bills, handle GST-compliant tax calculations, maintain "
        "your traditional credit ledger (Khata), close the day, and generate beautiful "
        "business PDF/PPTX artifacts on demand.\n\n"
        "<b>Core Commands:</b>\n"
        "• /new - Starts a fresh conversation context (your store data is kept safe!)\n"
        "• /help - Display the lists of things we can do\n\n"
        "<b>Try talking to me in natural language:</b>\n"
        "• <i>'Add 2 packets of Maggi and 5kg of Basmati Rice'</i>\n"
        "• <i>'Put ₹500 on Ramesh's credit'</i>\n"
        "• <i>'How much sugar is left?'</i>\n"
        "• <i>'Send me that bill as a PDF'</i> (generates a beautiful vector GST Invoice)\n"
        "• <i>'Make this week's sales analysis deck'</i> (compiles a PPTX with charts)"
    )
    # Clear conversation history for fresh start
    chat_sessions[chat_id] = []
    send_message(chat_id, welcome_text)

def handle_help_command(chat_id):
    help_text = (
        "<b>Available Operations:</b>\n\n"
        "<b>1. Billing & Sales</b>\n"
        "• 'make a bill: 2kg sugar, 4 packets of Maggi, UPI'\n"
        "• 'drop the butter, make it 6 Maggi'\n"
        "• 'finalize' or 'cut bill'\n\n"
        "<b>2. Stock & Inventory Management</b>\n"
        "• 'how much sugar is left?'\n"
        "• 'what is running out?'\n"
        "• '50 packets of Maggi came in, cost ₹12, MRP ₹14'\n"
        "• 'new item: Amul Butter 100g, GST 12%, MRP ₹62'\n\n"
        "<b>3. Customer Credit Ledger (Khata)</b>\n"
        "• 'put ₹500 on Ramesh's credit'\n"
        "• 'Ramesh paid ₹300'\n"
        "• 'what is Ramesh's balance?'\n\n"
        "<b>4. Close Day & Reports</b>\n"
        "• 'today's sales?' / 'close the day'\n"
        "• 'send me that bill as a PDF' (requires finalized sale)\n"
        "• 'generate a weekly business analysis deck'\n\n"
        "<b>5. Preferences</b>\n"
        "• 'always assume UPI unless I say cash'\n"
        "• 'default shop name is Sri Krishna Store'"
    )
    send_message(chat_id, help_text)

def process_telegram_update(update):
    if "message" not in update:
        return
        
    message = update["message"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "")
    
    if not text:
        return
        
    print(f"Received message from Chat ID {chat_id}: '{text}'")
    
    # Check for commands
    if text.startswith("/start"):
        handle_start_command(chat_id)
        return
    elif text.startswith("/new"):
        chat_sessions[chat_id] = []
        send_message(chat_id, "🧹 <b>Conversation history cleared!</b> Starting a new session. (All store databases, balances, and preferences are safely preserved.)")
        return
    elif text.startswith("/help"):
        handle_help_command(chat_id)
        return
        
    # Standard conversation turn routed through AI Agent
    if chat_id not in chat_sessions:
        chat_sessions[chat_id] = []
        
    # Show typing action to user for better UX
    try:
        requests.post(f"{API_URL}/sendChatAction", json={"chat_id": chat_id, "action": "typing"})
    except:
        pass
        
    # Get conversational response from Agent
    response_text, updated_history = agent.run_agent_loop(chat_id, text, chat_sessions[chat_id])
    chat_sessions[chat_id] = updated_history
    
    # Send textual response
    send_message(chat_id, response_text)
    
    # Post-processing: check if there are newly generated file artifacts in scratch to deliver!
    # The agent loops outputs can indicate if a PDF or PPTX has been generated.
    # We can detect keywords in the assistant message or look in the file directory.
    if "GST Invoice PDF successfully created" in response_text or "PDF Invoice" in response_text or "invoice_" in response_text:
        # Resolve sale_id from response or directory
        # Find latest invoice generated
        try:
            files = [f for f in os.listdir(SCRATCH_DIR) if f.startswith("invoice_") and f.endswith(".pdf")]
            if files:
                latest_file = sorted(files, key=lambda x: os.path.getmtime(os.path.join(SCRATCH_DIR, x)))[-1]
                filepath = os.path.join(SCRATCH_DIR, latest_file)
                send_document(chat_id, filepath, "📄 Here is your requested GST Tax Invoice PDF.")
        except Exception as e:
            print(f"Error checking and sending invoice PDF: {e}")
            
    elif "Weekly Store Performance PPTX" in response_text or "pptx report" in response_text.lower() or "analysis deck" in response_text.lower():
        filepath = os.path.join(SCRATCH_DIR, "weekly_analytics_report.pptx")
        if os.path.exists(filepath):
            send_document(chat_id, filepath, "📊 Here is your requested Weekly Store Analysis PPTX Presentation Deck.")

def run_polling():
    """Simple Telegram Bot Long-Polling loop"""
    if not TOKEN:
        print("CRITICAL ERROR: TELEGRAM_BOT_TOKEN environment variable is not configured. Exiting.")
        sys.exit(1)
        
    print("Sri Krishna Kirana Store AI Agent is polling for updates...")
    database.init_db()
    database.seed_database()
    
    offset = 0
    while True:
        try:
            r = requests.get(f"{API_URL}/getUpdates", params={"offset": offset, "timeout": 20}, timeout=30)
            res = r.json()
            if res.get("ok"):
                for update in res.get("result", []):
                    process_telegram_update(update)
                    offset = update["update_id"] + 1
            else:
                print(f"Error polling updates: {res.get('description')}")
        except KeyboardInterrupt:
            print("Stopping...")
            break
        except Exception as e:
            print(f"Polling loop connection error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    run_polling()
