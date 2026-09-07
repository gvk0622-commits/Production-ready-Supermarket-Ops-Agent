import os

SCRATCH_DIR = "/workspace/scratch" if os.path.exists("/workspace/scratch") else os.path.join(os.getcwd(), "scratch")
os.makedirs(SCRATCH_DIR, exist_ok=True)
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE
import database

# Clean Slate and Stone Color Palette (Custom professional design)
PALETTE = {
    'bg':         RGBColor(0xFA, 0xFA, 0xF9), # Stone Light
    'text':       RGBColor(0x0F, 0x17, 0x2A), # Slate 900
    'accent':     RGBColor(0x33, 0x41, 0x55), # Slate 700 (Primary accent)
    'accent_light': RGBColor(0xE2, 0xE8, 0xF0), # Slate 200
    'muted':      RGBColor(0x64, 0x74, 0x8B), # Slate 500
    'light':      RGBColor(0xF1, 0xF5, 0xF9), # Slate 100
    'font_title': 'Georgia',
    'font_body':  'Verdana'
}

def apply_text_styling(paragraph, font_name, font_size, bold=False, color=None, alignment=PP_ALIGN.LEFT):
    paragraph.alignment = alignment
    for run in paragraph.runs:
        run.font.name = font_name
        run.font.size = Pt(font_size)
        run.font.bold = bold
        if color:
            run.font.color.rgb = color

def add_formatted_bullet(text_frame, bullet_text, base_font_size=12):
    """Parses <b> and </b> tags in text and splits them into bold/normal runs in python-pptx"""
    p = text_frame.add_paragraph()
    p.space_after = Pt(8)
    p.alignment = PP_ALIGN.LEFT
    
    current = bullet_text
    parts = []
    
    while "<b>" in current:
        before, rest = current.split("<b>", 1)
        if "</b>" in rest:
            inside, after = rest.split("</b>", 1)
            if before:
                parts.append((before, False))
            parts.append((inside, True))
            current = after
        else:
            break
    if current:
        parts.append((current, False))
        
    if not parts:
        parts = [(bullet_text, False)]
        
    for text, is_bold in parts:
        run = p.add_run()
        run.text = text
        run.font.name = PALETTE['font_body']
        run.font.size = Pt(base_font_size)
        run.font.color.rgb = PALETTE['text']
        run.font.bold = is_bold

def add_slide_header(slide, action_title):
    """Adds a consistent, non-overlapping header with an action title"""
    title_box = slide.shapes.add_textbox(Inches(0.5), Inches(0.4), Inches(12.333), Inches(0.8))
    tf = title_box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = action_title
    apply_text_styling(p, PALETTE['font_title'], 22, bold=True, color=PALETTE['text'])
    
    # Accent thin line underneath
    accent_bar = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0.5), Inches(1.2), Inches(12.333), Pt(2.0)
    )
    accent_bar.fill.solid()
    accent_bar.fill.fore_color.rgb = PALETTE['accent']
    accent_bar.line.fill.background()

def set_slide_background(slide):
    bg = slide.background
    bg.fill.solid()
    bg.fill.fore_color.rgb = PALETTE['bg']

def generate_weekly_report_deck(filepath):
    """
    Generate a 100% dynamic, data-driven PPTX performance report.
    Pulls exact top sellers, debtor khata credit accounts, and actual inventory counts.
    """
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    
    # 1. Gather actual database values
    conn = database.get_connection()
    cursor = conn.cursor()
    
    # Total revenue, tax and transactions
    cursor.execute("SELECT SUM(total_amount) as rev, SUM(total_tax) as tax, COUNT(sale_id) as sales_count FROM sales")
    sales_summary = cursor.fetchone()
    total_rev = sales_summary["rev"] if sales_summary["rev"] else 0.0
    total_tax = sales_summary["tax"] if sales_summary["tax"] else 0.0
    sales_count = sales_summary["sales_count"] if sales_summary["sales_count"] else 0
    
    # Outstanding Khata Credit Book
    cursor.execute("SELECT SUM(balance) as total_credit FROM khata")
    credit_summary = cursor.fetchone()
    total_outstanding = credit_summary["total_credit"] if credit_summary["total_credit"] else 0.0
    
    # Top-selling items sold
    cursor.execute("""
        SELECT name, SUM(si.quantity) as qty, SUM(si.quantity * si.price) as revenue 
        FROM sale_items si 
        JOIN inventory inv ON si.sku_id = inv.sku_id 
        GROUP BY si.sku_id 
        ORDER BY qty DESC LIMIT 5
    """)
    top_items = cursor.fetchall()
    
    # Low Stock Items
    cursor.execute("SELECT name, quantity, unit, reorder_level FROM inventory WHERE quantity <= reorder_level")
    low_stock = cursor.fetchall()
    
    # Highest Debtor
    cursor.execute("SELECT name, balance FROM khata ORDER BY balance DESC LIMIT 1")
    top_debtor_row = cursor.fetchone()
    top_debtor_name = top_debtor_row["name"] if top_debtor_row else "No active balances"
    top_debtor_bal = top_debtor_row["balance"] if top_debtor_row else 0.0
    
    conn.close()
    
    # -------------------------------------------------------------
    # SLIDE 1: TITLE SLIDE
    # -------------------------------------------------------------
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_background(slide)
    
    strip = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(0.4), Inches(7.5))
    strip.fill.solid()
    strip.fill.fore_color.rgb = PALETTE['accent']
    strip.line.fill.background()
    
    title_box = slide.shapes.add_textbox(Inches(1.2), Inches(2.2), Inches(11.0), Inches(3.0))
    tf = title_box.text_frame
    tf.word_wrap = True
    
    p1 = tf.paragraphs[0]
    p1.text = "SRI KRISHNA KIRANA STORE"
    apply_text_styling(p1, PALETTE['font_title'], 38, bold=True, color=PALETTE['accent'])
    p1.space_after = Pt(10)
    
    p2 = tf.add_paragraph()
    p2.text = "Weekly Performance, Inventory Health & Credit Analysis"
    apply_text_styling(p2, PALETTE['font_body'], 18, bold=False, color=PALETTE['muted'])
    p2.space_after = Pt(20)
    
    p3 = tf.add_paragraph()
    p3.text = "Generated dynamically by Supermarket Ops AI Agent | Coimbatore, TN"
    apply_text_styling(p3, PALETTE['font_body'], 11, bold=True, color=PALETTE['accent'])
    
    # -------------------------------------------------------------
    # SLIDE 2: KPI CARDS SLIDE
    # -------------------------------------------------------------
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_background(slide)
    add_slide_header(slide, f"Weekly sales totaled ₹{total_rev:,.2f} with outstanding credit of ₹{total_outstanding:,.2f}")
    
    card_w, card_h = Inches(3.6), Inches(2.5)
    gap = Inches(0.5)
    start_left = Inches(0.7)
    card_y = Inches(2.2)
    
    kpis = [
        ("STORE SALES REVENUE", f"₹{total_rev:,.2f}", f"Across {sales_count} Transactions"),
        ("GST TAX COLLECTED", f"₹{total_tax:,.2f}", "Intrastate CGST/SGST 50/50"),
        ("KHATA CREDIT BALANCES", f"₹{total_outstanding:,.2f}", "Outstanding customer book value")
    ]
    
    for idx, (title, value, sub) in enumerate(kpis):
        left_pos = start_left + idx * (card_w + gap)
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left_pos, card_y, card_w, card_h)
        card.fill.solid()
        card.fill.fore_color.rgb = PALETTE['light']
        card.line.color.rgb = PALETTE['accent'] if idx == 0 else PALETTE['muted']
        card.line.width = Pt(1.5) if idx == 0 else Pt(0.5)
        
        tf = card.text_frame
        tf.word_wrap = True
        
        p_title = tf.paragraphs[0]
        p_title.text = title
        p_title.space_after = Pt(14)
        apply_text_styling(p_title, PALETTE['font_body'], 12, bold=True, color=PALETTE['muted'], alignment=PP_ALIGN.CENTER)
        
        p_val = tf.add_paragraph()
        p_val.text = value
        p_val.space_after = Pt(14)
        apply_text_styling(p_val, PALETTE['font_title'], 28, bold=True, color=PALETTE['accent'], alignment=PP_ALIGN.CENTER)
        
        p_sub = tf.add_paragraph()
        p_sub.text = sub
        apply_text_styling(p_sub, PALETTE['font_body'], 10, bold=False, color=PALETTE['muted'], alignment=PP_ALIGN.CENTER)
        
    # -------------------------------------------------------------
    # SLIDE 3: VISUAL ANALYSIS
    # -------------------------------------------------------------
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_background(slide)
    
    names = [item["name"][:15] for item in top_items] if top_items else ["No Sales"]
    revs = [item["revenue"] for item in top_items] if top_items else [0.0]
    
    plt.figure(figsize=(6, 4))
    colors_list = ['#334155', '#475569', '#64748B', '#94A3B8', '#CBD5E1']
    plt.bar(names, revs, color=colors_list[:len(names)], width=0.5)
    plt.title("Revenue by Top Selling Items (₹)", fontsize=11, fontweight='bold', color='#0F172A', pad=10)
    plt.xticks(rotation=15, fontsize=8, color='#64748B')
    plt.yticks(fontsize=8, color='#64748B')
    plt.gca().spines['top'].set_visible(False)
    plt.gca().spines['right'].set_visible(False)
    plt.gca().spines['left'].set_color('#94A3B8')
    plt.gca().spines['bottom'].set_color('#94A3B8')
    plt.tight_layout()
    
    chart_path = os.path.join(SCRATCH_DIR, "weekly_top_items.png")
    plt.savefig(chart_path, dpi=200, transparent=True)
    plt.close()
    
    add_slide_header(slide, "Fast-moving inventory lines drive the major share of daily grocery revenue")
    slide.shapes.add_picture(chart_path, Inches(0.7), Inches(2.0), width=Inches(5.8))
    
    text_box = slide.shapes.add_textbox(Inches(7.0), Inches(2.0), Inches(5.6), Inches(4.5))
    tf = text_box.text_frame
    tf.word_wrap = True
    
    p_head = tf.paragraphs[0]
    p_head.text = "SALES COMPOSITION & ANALYSIS"
    apply_text_styling(p_head, PALETTE['font_body'], 14, bold=True, color=PALETTE['accent'])
    p_head.space_after = Pt(12)
    
    if top_items:
        t1 = top_items[0]
        b1 = f"• <b>Volume Leader</b>: <b>{t1['name']}</b> has emerged as our top selling SKU with a volume of <b>{t1['qty']} units</b>, contributing <b>₹{t1['revenue']:.2f}</b> to this week's gross sales."
        if len(top_items) > 1:
            t2 = top_items[1]
            b2 = f"• <b>Secondary Velocity</b>: <b>{t2['name']}</b> has recorded steady volumes of <b>{t2['qty']} units</b>, contributing <b>₹{t2['revenue']:.2f}</b> to the total cash flow."
        else:
            b2 = "• <b>Revenue Distribution</b>: Packaged FMCGs and grocery items are currently carrying the store velocity."
        b3 = f"• <b>Compliance Breakdown</b>: Out of our weekly receipts, dynamic CGST and SGST splits generated a total tax compliance collection of <b>₹{total_tax:.2f}</b>."
    else:
        b1 = "• <b>No Active Transactions</b>: Seed store sales to generate dynamic top-selling item details on this slide."
        b2 = "• <b>Volume Monitoring</b>: Store staples are tracked via SKU transaction logs for on-shelf inventory monitoring."
        b3 = "• <b>Statutory Collections</b>: Inter-state vs intra-state GST is calculated and aggregated automatically."
        
    for pt in [b1, b2, b3]:
        add_formatted_bullet(tf, pt)
        
    # -------------------------------------------------------------
    # SLIDE 4: INVENTORY ALERT & REORDER SLIDE
    # -------------------------------------------------------------
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_background(slide)
    
    low_stock_count = len(low_stock)
    reorder_text = f"{low_stock_count} essential SKU{'s are' if low_stock_count != 1 else ' is'} running low and require prompt reorder" if low_stock_count > 0 else "All essential SKU stock reserves are healthy"
    add_slide_header(slide, reorder_text)
    
    rows_num = max(2, low_stock_count + 1)
    table_shape = slide.shapes.add_table(rows_num, 4, Inches(0.7), Inches(2.0), Inches(6.0), Inches(4.5))
    table = table_shape.table
    table.columns[0].width = Inches(2.5) # Name
    table.columns[1].width = Inches(1.1) # Qty Left
    table.columns[2].width = Inches(1.1) # Min Level
    table.columns[3].width = Inches(1.3) # Action
    
    headers = ["Item Name", "Qty Left", "Reorder Level", "Action Code"]
    for idx, name in enumerate(headers):
        cell = table.cell(0, idx)
        cell.text = name
        cell.fill.solid()
        cell.fill.fore_color.rgb = PALETTE['accent']
        p = cell.text_frame.paragraphs[0]
        apply_text_styling(p, PALETTE['font_body'], 11, bold=True, color=RGBColor(255,255,255), alignment=PP_ALIGN.CENTER)
        
    if low_stock_count > 0:
        for r_idx, item in enumerate(low_stock):
            row_idx = r_idx + 1
            table.cell(row_idx, 0).text = item["name"]
            table.cell(row_idx, 1).text = f"{item['quantity']} {item['unit']}"
            table.cell(row_idx, 2).text = f"{item['reorder_level']} {item['unit']}"
            table.cell(row_idx, 3).text = "REORDER NOW"
            
            for c_idx in range(4):
                cell = table.cell(row_idx, c_idx)
                cell.fill.solid()
                cell.fill.fore_color.rgb = PALETTE['light'] if row_idx % 2 == 0 else RGBColor(255,255,255)
                p = cell.text_frame.paragraphs[0]
                text_color = PALETTE['text']
                if c_idx == 3:
                    text_color = RGBColor(185, 28, 28)
                apply_text_styling(p, PALETTE['font_body'], 10, bold=(c_idx==3), color=text_color, alignment=PP_ALIGN.CENTER)
    else:
        table.cell(1, 0).text = "All products have adequate stock levels."
        table.cell(1, 1).text = "-"
        table.cell(1, 2).text = "-"
        table.cell(1, 3).text = "HEALTHY"
        for c_idx in range(4):
            cell = table.cell(1, c_idx)
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(255,255,255)
            p = cell.text_frame.paragraphs[0]
            apply_text_styling(p, PALETTE['font_body'], 10, bold=False, color=PALETTE['muted'], alignment=PP_ALIGN.CENTER)
            
    strategy_box = slide.shapes.add_textbox(Inches(7.2), Inches(2.0), Inches(5.4), Inches(4.5))
    tf_strat = strategy_box.text_frame
    tf_strat.word_wrap = True
    
    p_st = tf_strat.paragraphs[0]
    p_st.text = "INVENTORY PROTECTION PROTOCOLS"
    apply_text_styling(p_st, PALETTE['font_body'], 14, bold=True, color=PALETTE['accent'])
    p_st.space_after = Pt(12)
    
    if low_stock_count > 0:
        low_names = [f"<b>{i['name']}</b>" for i in low_stock[:2]]
        l1 = f"• <b>Critical Replenishment Priority</b>: {', '.join(low_names)} have dropped below reorder margins. Order fresh stock units."
        l2 = "• <b>Expiration Protection</b>: Implement strict FEFO / shelf rotation protocols on replenished stocks to safeguard product quality."
        l3 = f"• <b>Suppliers Consolidation</b>: Aggregate orders for these {low_stock_count} item groups to lower freight costs and keep high shelf availability."
    else:
        l1 = "• <b>No Immediate Procurement</b>: Safe stock thresholds are maintained across all departments."
        l2 = "• <b>FEFO Principles Active</b>: Daily replenishment rotations continue under FIFO criteria."
        l3 = "• <b>Monitoring Frequency</b>: AI keeps tracking sales velocity to generate future safety level notifications."
        
    for pt in [l1, l2, l3]:
        add_formatted_bullet(tf_strat, pt)
        
    # -------------------------------------------------------------
    # SLIDE 5: ACTIONS / RECOMMENDATIONS
    # -------------------------------------------------------------
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_background(slide)
    add_slide_header(slide, "Prioritize credit recoveries and restock popular high-velocity FMCG items")
    
    rec_box = slide.shapes.add_textbox(Inches(0.7), Inches(2.0), Inches(11.9), Inches(4.5))
    tf_rec = rec_box.text_frame
    tf_rec.word_wrap = True
    
    p_rec_head = tf_rec.paragraphs[0]
    p_rec_head.text = "IMMEDIATE BUSINESS ACTION ITEMS"
    apply_text_styling(p_rec_head, PALETTE['font_body'], 15, bold=True, color=PALETTE['accent'])
    p_rec_head.space_after = Pt(14)
    
    r1 = f"• <b>Proactive Khata Credit Recovery</b>: Customer <b>{top_debtor_name}</b> holds our highest outstanding ledger balance of <b>₹{top_debtor_bal:.2f}</b> (Total outstanding: ₹{total_outstanding:.2f}). Issue polite reminders and link direct digital UPI codes to accelerate settlement flow."
    r2 = "• <b>Multi-turn Checkout Polish</b>: Educate shopgoers to utilize the open conversational draft to accumulate orders across the day and check out in a single final transaction, reducing counter queues."
    
    if low_stock_count > 0:
        r3 = f"• <b>Replenish Safety Stock</b>: Complete a wholesale procurement ticket for <b>{low_stock[0]['name']}</b> and low-stock staples to avoid stockout friction during high weekend demands."
    else:
        r3 = "• <b>Aisle Velocity Campaigns</b>: Launch promotional loyalty bundle sales across FMCG packets and packaged grains to maximize daily cash and UPI flows."
        
    for r_text in [r1, r2, r3]:
        add_formatted_bullet(tf_rec, r_text, base_font_size=13)
        
    prs.save(filepath)
    return filepath
