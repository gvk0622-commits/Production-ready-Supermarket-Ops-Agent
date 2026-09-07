import os
from dotenv import load_dotenv
load_dotenv()

SCRATCH_DIR = "/workspace/scratch" if os.path.exists("/workspace/scratch") else os.path.join(os.getcwd(), "scratch")
os.makedirs(SCRATCH_DIR, exist_ok=True)
import json
from openai import OpenAI
import database
import billing_engine
import pdf_generator
import pptx_generator

# Flexible Client Initialization (supports standard OpenAI and free OpenRouter keys)
if os.environ.get("OPENROUTER_API_KEY"):
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ.get("OPENROUTER_API_KEY")
    )
    DEFAULT_MODEL = "openrouter/free"
else:
    client = OpenAI()
    DEFAULT_MODEL = "gpt-4o"

# Define the schemas for our Agent's Tools
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "add_item_to_bill",
            "description": "Add an item to the active draft bill. Handles loose and packaged items using fuzzy text search on the SKU database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_text": {"type": "string", "description": "The item name or SKU ID (e.g. 'Aashirvaad Atta', 'Maggi', 'Sugar')"},
                    "quantity": {"type": "number", "description": "Quantity to add (default is 1.0)"}
                },
                "required": ["query_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_bill_item",
            "description": "Modify or drop an item in the active draft bill mid-build.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_text": {"type": "string", "description": "Fuzzy name of the item or SKU ID"},
                    "action": {"type": "string", "enum": ["SET_QTY", "DROP_ITEM"], "description": "Action: SET_QTY to change quantity, DROP_ITEM to remove the product"},
                    "quantity_val": {"type": "number", "description": "New quantity value (required for SET_QTY)"}
                },
                "required": ["query_text", "action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "finalize_active_bill",
            "description": "Finalize the draft bill, execute the transaction, decrement database inventory, and log the sale. If credit, update Customer's credit ledger (Khata).",
            "parameters": {
                "type": "object",
                "properties": {
                    "payment_mode": {"type": "string", "enum": ["CASH", "UPI", "CARD", "CREDIT"], "description": "Payment mode used"},
                    "customer_name": {"type": "string", "description": "Customer name (required for CREDIT payment mode)"}
                },
                "required": ["payment_mode"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_stock_status",
            "description": "Query how much quantity of an item is left in the store.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_text": {"type": "string", "description": "Name or SKU ID of the item"}
                },
                "required": ["query_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_low_stock_report",
            "description": "Identify products running low on stock (at or below reorder levels).",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_new_inventory_item",
            "description": "Add a brand new product SKU to the database with its core details and HSN/tax details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku_id": {"type": "string", "description": "Unique uppercase identifier e.g. AMUL_MILK_500ML"},
                    "name": {"type": "string", "description": "Full product description name"},
                    "cost_price": {"type": "number", "description": "Merchant cost price in ₹"},
                    "mrp": {"type": "number", "description": "Maximum Retail Price in ₹"},
                    "sell_price": {"type": "number", "description": "Actual store selling price in ₹ (inclusive of tax)"},
                    "quantity": {"type": "number", "description": "Initial stock quantity"},
                    "unit": {"type": "string", "description": "Unit of measurement e.g. packet, piece, kg, litre"},
                    "reorder_level": {"type": "number", "description": "Minimum threshold before low stock trigger"},
                    "gst_rate": {"type": "number", "description": "GST rate percentage (e.g., 0.0, 5.0, 12.0, 18.0)"},
                    "hsn_code": {"type": "string", "description": "Tax classification HSN code"}
                },
                "required": ["sku_id", "name", "cost_price", "mrp", "sell_price", "quantity", "unit", "reorder_level", "gst_rate", "hsn_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "receive_stock_consignment",
            "description": "Adjust stock quantity upwards for an existing SKU (receiving new wholesale stock).",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku_id": {"type": "string", "description": "The SKU code"},
                    "quantity_change": {"type": "number", "description": "Number of units to ADD to the stock"}
                },
                "required": ["sku_id", "quantity_change"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_khata_record",
            "description": "Retrieve customer credit balance, record a new credit purchase, or log a customer payment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "The customer's name"},
                    "action": {"type": "string", "enum": ["GET_BALANCE", "RECORD_PAYMENT", "RECORD_CREDIT"], "description": "Action type"},
                    "amount": {"type": "number", "description": "The payment or credit amount (not required for GET_BALANCE)"}
                },
                "required": ["customer_name", "action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_business_report_artifacts",
            "description": "Generate business artifacts: PDF GST invoice for a finalized sale, or PPTX performance analysis deck.",
            "parameters": {
                "type": "object",
                "properties": {
                    "artifact_type": {"type": "string", "enum": ["PDF_INVOICE", "PPTX_ANALYTICS_DECK"], "description": "The artifact file to generate"},
                    "sale_id": {"type": "integer", "description": "Finalized Sale ID (required only for PDF_INVOICE)"}
                },
                "required": ["artifact_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_store_preference",
            "description": "Store a persistent preference for the shop (e.g. preferred default payment mode, default brands, shop name, gstin).",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "The preference key (e.g. 'default_payment_mode', 'shop_name', 'shop_gstin')"},
                    "value": {"type": "string", "description": "The preference value (e.g. 'UPI', 'Amul', 'Sri Krishna Store')"}
                },
                "required": ["key", "value"]
            }
        }
    }
]

def execute_tool_call(tool_name, arguments, chat_id):
    """Router that handles dynamic tool execution with structured return codes and errors"""
    try:
        if tool_name == "add_item_to_bill":
            qty = arguments.get("quantity", 1.0)
            item_name, total_qty, unit = billing_engine.add_item_to_draft(chat_id, arguments["query_text"], qty)
            return {"status": "SUCCESS", "message": f"Added {qty} of '{item_name}' to the bill. Draft now has {total_qty} {unit}."}
            
        elif tool_name == "edit_bill_item":
            res_msg = billing_engine.edit_item_in_draft(chat_id, arguments["query_text"], arguments["action"], arguments.get("quantity_val"))
            return {"status": "SUCCESS", "message": res_msg}
            
        elif tool_name == "finalize_active_bill":
            payment_mode = arguments["payment_mode"]
            customer_name = arguments.get("customer_name")
            sale_id, totals, status = billing_engine.finalize_bill(chat_id, payment_mode, customer_name)
            return {
                "status": "SUCCESS",
                "sale_id": sale_id,
                "totals": totals,
                "message": f"Bill #{sale_id} successfully finalized via {payment_mode}! Total Amount: ₹{totals['total_amount']:.2f}, GST: ₹{totals['tax_total']:.2f}."
            }
            
        elif tool_name == "query_stock_status":
            sku_info = database.query_sku(arguments["query_text"])
            if not sku_info:
                return {"status": "ERROR", "message": f"Product '{arguments['query_text']}' not found."}
            if isinstance(sku_info, list):
                if len(sku_info) > 1:
                    opts = [f"{s['name']} (Stock: {s['quantity']})" for s in sku_info]
                    return {"status": "AMBIGUOUS", "message": f"Multiple options found. Please choose:", "options": opts}
                sku_info = sku_info[0]
            return {"status": "SUCCESS", "message": f"Product: {sku_info['name']} has {sku_info['quantity']} {sku_info['unit']} left in stock. MRP: ₹{sku_info['mrp']}."}
            
        elif tool_name == "get_low_stock_report":
            low_items = database.get_low_stock_items()
            if not low_items:
                return {"status": "SUCCESS", "message": "All items have healthy stock levels."}
            report = [f"• {i['name']}: {i['quantity']} {i['unit']} left (Reorder level: {i['reorder_level']})" for i in low_items]
            return {"status": "SUCCESS", "items": low_items, "message": "\n".join(report)}
            
        elif tool_name == "add_new_inventory_item":
            database.add_new_sku(
                arguments["sku_id"], arguments["name"], arguments["cost_price"],
                arguments["mrp"], arguments["sell_price"], arguments["quantity"],
                arguments["unit"], arguments["reorder_level"], arguments["gst_rate"], arguments["hsn_code"]
            )
            return {"status": "SUCCESS", "message": f"Successfully registered new SKU '{arguments['name']}' in inventory."}
            
        elif tool_name == "receive_stock_consignment":
            database.update_stock_quantity(arguments["sku_id"], arguments["quantity_change"])
            return {"status": "SUCCESS", "message": f"Successfully adjusted stock for SKU '{arguments['sku_id']}' upwards by {arguments['quantity_change']} units."}
            
        elif tool_name == "manage_khata_record":
            customer_name = arguments["customer_name"]
            action = arguments["action"]
            amount = arguments.get("amount", 0.0)
            
            if action == "GET_BALANCE":
                custs = database.get_khata_customer(customer_name)
                if not custs:
                    return {"status": "ERROR", "message": f"No credit ledger (Khata) found for '{customer_name}'."}
                return {"status": "SUCCESS", "message": f"Customer '{custs[0]['name']}' has an outstanding credit balance of ₹{custs[0]['balance']:.2f}."}
                
            elif action == "RECORD_PAYMENT":
                new_balance = database.record_khata_payment(customer_name, amount)
                return {"status": "SUCCESS", "message": f"Recorded payment of ₹{amount:.2f} for '{customer_name}'. Outstanding ledger balance is now ₹{new_balance:.2f}."}
                
            elif action == "RECORD_CREDIT":
                database.record_khata_credit(customer_name, amount)
                custs = database.get_khata_customer(customer_name)
                return {"status": "SUCCESS", "message": f"Recorded credit purchase of ₹{amount:.2f} on '{customer_name}'s account. Total outstanding: ₹{custs[0]['balance']:.2f}."}
                
        elif tool_name == "generate_business_report_artifacts":
            a_type = arguments["artifact_type"]
            if a_type == "PDF_INVOICE":
                sale_id = arguments.get("sale_id")
                if not sale_id:
                    return {"status": "ERROR", "message": "Sale ID is required to generate a PDF invoice."}
                filename = f"invoice_{sale_id}.pdf"
                filepath = os.path.join(SCRATCH_DIR, filename)
                pdf_generator.generate_invoice_pdf(sale_id, filepath)
                return {"status": "SUCCESS", "filepath": filepath, "message": f"GST Invoice PDF successfully created for Sale #{sale_id}."}
                
            elif a_type == "PPTX_ANALYTICS_DECK":
                filepath = os.path.join(SCRATCH_DIR, "weekly_analytics_report.pptx")
                pptx_generator.generate_weekly_report_deck(filepath)
                return {"status": "SUCCESS", "filepath": filepath, "message": "Weekly Store Performance PPTX report deck successfully generated with analytical charts."}
                
        elif tool_name == "set_store_preference":
            database.set_preference(arguments["key"], arguments["value"])
            return {"status": "SUCCESS", "message": f"Standing preference '{arguments['key']}' saved as '{arguments['value']}' persistently."}
            
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

def run_agent_loop(chat_id, user_text, conversation_history=None):
    """
    Core Observe-Reason-Act loop:
    1. Send user text + system instructions + dynamic tools schema to LLM
    2. Model emits tool calls
    3. Python executes tools dynamically, appends results
    4. Model observes tool outputs, decides to execute more tools or produce conversational response
    """
    if conversation_history is None:
        conversation_history = []
        
    system_prompt = """
    You are Sri Krishna Kirana Store's AI Ops Specialist. You run the store end-to-end for the owner entirely through text.
    You do NOT use regular expressions or simple routers. You reason over natural, messy, storekeeper phrasing.
    
    CRITICAL FORMATTING & DESIGN RULES (PREVENTS USER DISPLAY ISSUES):
    1. Do NOT use raw Markdown bold markers like `**` or header characters like `###` in any conversational responses. 
       Since we run in Telegram under HTML parse mode, raw `**` will be displayed as literal characters which looks unprofessional. 
       Instead, use standard HTML bold tags like `<b>` and `</b>` if you need to emphasize something. Keep units (e.g. kg, packet, piece) and weights completely clean and unbolded unless absolutely necessary.
    2. Do NOT use Markdown tables (e.g. using `|` or hyphens) in your checkout summaries or finalized bill messages. 
       On mobile screens, Markdown tables get clipped and wrapped messily. 
       Instead, format the bill summary using a clean, indented, structured plain-text list of items. 
       Example of a clean text summary list:
       
       Bill #1 Summary:
       • Product Name: 10 kg @ ₹42/kg (5% GST: ₹20.00) -> Total: ₹420.00
       
       Subtotal: ₹400.00
       CGST Rate/Amt (2.5%): ₹10.00
       SGST Rate/Amt (2.5%): ₹10.00
       Total GST: ₹20.00
       Total Paid via UPI: ₹420.00
       
    CRITICAL BUSINESS BEHAVIORS:
    1. Grounding: Prices, stock, and GST come from database tools. Never make up a product, price, or GST.
    2. Clarification: If the user says 'add atta' and multiple attas exist, ask a clarifying question from the model listing the options.
    3. Multi-turn billing: Allow the user to build a bill across several messages. Stock is NOT decremented until finalized.
    4. Business logic: Concurrency, stock oversell checks, and ledger limits are enforced in tools, but you must report them politely.
    5. Intrastate GST standard split: CGST and SGST must split the item tax rate equally (e.g. 5% GST = 2.5% CGST + 2.5% SGST). Both columns must show CGST/SGST split details.
    """
    
    messages = [{"role": "system", "content": system_prompt}] + conversation_history + [{"role": "user", "content": user_text}]
    
    for loop_idx in range(5):
        try:
            model_slug = os.environ.get("AGENT_MODEL", DEFAULT_MODEL)
            
            response = client.chat.completions.create(
                model=model_slug,
                messages=messages,
                tools=TOOLS_SCHEMA,
                tool_choice="auto"
            )
        except Exception as e:
            return f"Agent connection error: Please configure OPENAI_API_KEY or OPENROUTER_API_KEY environment variable. Details: {str(e)}", conversation_history
            
        msg = response.choices[0].message
        messages.append(msg)
        
        if not msg.tool_calls:
            conversation_history.append({"role": "assistant", "content": msg.content})
            return msg.content, conversation_history
            
        for tool_call in msg.tool_calls:
            tool_name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            
            tool_res = execute_tool_call(tool_name, args, chat_id)
            
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_name,
                "content": json.dumps(tool_res)
            })
            
            print(f"Tool executed: {tool_name}({args}) -> Result: {tool_res['status']}")
            
    fallback_res = "I am processing several items but to avoid loop overflows, please specify your next action."
    conversation_history.append({"role": "assistant", "content": fallback_res})
    return fallback_res, conversation_history
