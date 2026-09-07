import os
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
)
import database
import billing_engine

# Minimalist, highly professional Slate Palette (replaces heavy teal block)
COLORS = {
    'heading':    HexColor('#0F172A'), # Slate 900
    'body':       HexColor('#334155'), # Slate 700
    'accent':     HexColor('#475569'), # Slate 600
    'muted':      HexColor('#64748B'), # Slate 500
    'bg_alt':     HexColor('#F8FAFC'), # Slate 50
    'bg_header':  HexColor('#334155'), # Slate 700 (softer table header)
    'white':      HexColor('#FFFFFF'),
    'border':     HexColor('#E2E8F0')  # Slate 200 (much lighter grid borders)
}

HEADING_FONT = 'Helvetica-Bold'
BODY_FONT    = 'Helvetica'

def generate_invoice_pdf(sale_id, filepath):
    """
    Generate an ultra-clean, minimalist GST-compliant PDF invoice.
    Uses dynamic CGST/SGST rate labels to resolve percentage symbol requests.
    """
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sales WHERE sale_id = ?", (sale_id,))
    sale = cursor.fetchone()
    if not sale:
        conn.close()
        raise KeyError(f"Sale ID {sale_id} not found.")
        
    cursor.execute("""
        SELECT si.*, inv.name, inv.unit, inv.hsn_code 
        FROM sale_items si 
        JOIN inventory inv ON si.sku_id = inv.sku_id 
        WHERE si.sale_id = ?
    """, (sale_id,))
    sale_items = cursor.fetchall()
    conn.close()
    
    # Get store preferences
    shop_name = database.get_preference("shop_name", "Sri Krishna Kirana Store")
    shop_gstin = database.get_preference("shop_gstin", "33AAAAA1111A1Z0")
    
    draft_items = []
    for item in sale_items:
        draft_items.append({
            "sku_id": item["sku_id"],
            "name": item["name"],
            "sell_price": item["price"],
            "quantity": item["quantity"],
            "unit": item["unit"],
            "gst_rate": item["gst_rate"],
            "hsn_code": item["hsn_code"]
        })
    draft = {"items": draft_items, "customer_id": None, "payment_mode": sale["payment_mode"]}
    totals = billing_engine.calculate_draft_totals(draft)
    
    doc = SimpleDocTemplate(
        filepath,
        pagesize=LETTER,
        leftMargin=36, rightMargin=36,
        topMargin=36, bottomMargin=36
    )
    
    USABLE_W = 540
    styles = getSampleStyleSheet()
    
    # Styles
    meta_style = ParagraphStyle(
        'InvoiceMeta', fontName=BODY_FONT, fontSize=9,
        textColor=COLORS['body'], leading=12
    )
    table_head_style = ParagraphStyle(
        'InvoiceTableHead', fontName=HEADING_FONT, fontSize=8,
        textColor=COLORS['white'], leading=10, alignment=TA_CENTER
    )
    table_body_style = ParagraphStyle(
        'InvoiceTableBody', fontName=BODY_FONT, fontSize=8,
        textColor=COLORS['body'], leading=10
    )
    table_body_center_style = ParagraphStyle(
        'InvoiceTableBodyCenter', fontName=BODY_FONT, fontSize=8,
        textColor=COLORS['body'], leading=10, alignment=TA_CENTER
    )
    table_body_right_style = ParagraphStyle(
        'InvoiceTableBodyRight', fontName=BODY_FONT, fontSize=8,
        textColor=COLORS['body'], leading=10, alignment=TA_RIGHT
    )
    total_label_style = ParagraphStyle(
        'InvoiceTotalLabel', fontName=HEADING_FONT, fontSize=9,
        textColor=COLORS['heading'], leading=12, alignment=TA_RIGHT
    )
    total_val_style = ParagraphStyle(
        'InvoiceTotalVal', fontName=HEADING_FONT, fontSize=9,
        textColor=COLORS['bg_header'], leading=12, alignment=TA_RIGHT
    )
    
    story = []
    
    header_data = [
        [
            Paragraph(f"<b>{shop_name}</b><br/>"
                      f"<font color='{COLORS['muted']}'>GSTIN: {shop_gstin}</font><br/>"
                      f"Coimbatore, Tamil Nadu, India", meta_style),
            Paragraph("<font size=16 color='#334155'><b>TAX INVOICE</b></font><br/>"
                      f"Invoice No: <b>#INV-2026-{sale_id:04d}</b><br/>"
                      f"Date: {sale['timestamp'][:10]}<br/>"
                      f"Time: {sale['timestamp'][11:16]}", meta_style)
        ]
    ]
    header_table = Table(header_data, colWidths=[300, 240])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 10))
    
    # Accent dividing bar
    story.append(Table([[""]], colWidths=[USABLE_W], rowHeights=[1.5], style=TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), COLORS['accent']),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
    ])))
    story.append(Spacer(1, 10))
    
    # Billed To
    payment_mode = sale["payment_mode"]
    pay_ref = sale["payment_ref"] if sale["payment_ref"] else "N/A"
    customer_info = "Walk-in Customer"
    if payment_mode == "CREDIT":
        cursor_khata = database.get_connection().cursor()
        cursor_khata.execute("""
            SELECT name, balance FROM khata 
            WHERE customer_id = (
                SELECT customer_id FROM khata_transactions 
                WHERE timestamp LIKE ? AND type='CREDIT' LIMIT 1
            )
        """, (f"{sale['timestamp'][:19]}%",))
        cust = cursor_khata.fetchone()
        if cust:
            customer_info = f"<b>{cust['name']} (Khata Account)</b><br/>Current Balance: ₹{cust['balance']:.2f}"
        database.get_connection().close()
        
    meta_data = [
        [
            Paragraph(f"<b>Billed To:</b><br/>{customer_info}", meta_style),
            Paragraph(f"<b>Payment Details:</b><br/>"
                      f"Mode: <b>{payment_mode}</b><br/>"
                      f"Reference: <font size=7>{pay_ref}</font>", meta_style)
        ]
    ]
    meta_table = Table(meta_data, colWidths=[300, 240])
    meta_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 14))
    
    # Main billing table with split CGST/SGST rates and clean columns
    col_widths = [25, 135, 40, 45, 55, 40, 55, 55, 90]
    headers = [
        Paragraph("<b>S.No</b>", table_head_style),
        Paragraph("<b>Item Description</b>", table_head_style),
        Paragraph("<b>HSN</b>", table_head_style),
        Paragraph("<b>Qty</b>", table_head_style),
        Paragraph("<b>Price</b>", table_head_style),
        Paragraph("<b>GST</b>", table_head_style),
        Paragraph("<b>CGST</b>", table_head_style),
        Paragraph("<b>SGST</b>", table_head_style),
        Paragraph("<b>Total (₹)</b>", table_head_style)
    ]
    
    rows = [headers]
    for idx, item in enumerate(totals["items"]):
        cgst_rate = item["gst_rate"] / 2.0
        sgst_rate = item["gst_rate"] / 2.0
        row_data = [
            Paragraph(f"{idx+1}", table_body_center_style),
            Paragraph(item["name"], table_body_style),
            Paragraph(item["hsn_code"], table_body_center_style),
            Paragraph(f"{item['quantity']} {item['unit']}", table_body_center_style),
            Paragraph(f"₹{item['sell_price']:.2f}", table_body_right_style),
            Paragraph(f"{item['gst_rate']}%", table_body_center_style),
            Paragraph(f"{cgst_rate:.1f}%<br/>₹{item['cgst']:.2f}", table_body_right_style),
            Paragraph(f"{sgst_rate:.1f}%<br/>₹{item['sgst']:.2f}", table_body_right_style),
            Paragraph(f"₹{item['total']:.2f}", table_body_right_style)
        ]
        rows.append(row_data)
        
    bill_table = Table(rows, colWidths=col_widths, repeatRows=1)
    bill_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), COLORS['bg_header']),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [COLORS['white'], COLORS['bg_alt']]),
        ('GRID', (0,0), (-1,-1), 0.5, COLORS['border']),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(bill_table)
    story.append(Spacer(1, 10))
    
    summary_data = [
        [
            Paragraph("<b>Terms & Declarations:</b><br/>"
                      "<font size=7 color='#64748B'>"
                      "1. Certified that items are described correctly and taxes are fully compliant.<br/>"
                      "2. Goods once sold cannot be taken back or exchanged.<br/>"
                      "3. Subject to Coimbatore jurisdiction.</font>", meta_style),
            Table([
                [Paragraph("Base Amount:", total_label_style), Paragraph(f"₹{totals['subtotal']:.2f}", total_body_style_right())],
                [Paragraph("CGST Total:", total_label_style), Paragraph(f"₹{totals['cgst_total']:.2f}", total_body_style_right())],
                [Paragraph("SGST Total:", total_label_style), Paragraph(f"₹{totals['sgst_total']:.2f}", total_body_style_right())],
                [Paragraph("<b>Grand Total:</b>", total_label_style), Paragraph(f"<b>₹{totals['total_amount']:.2f}</b>", total_val_style)]
            ], colWidths=[130, 90], style=TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('LINEBELOW', (0,0), (-1,-2), 0.3, COLORS['border']),
                ('LINEBELOW', (0,-1), (-1,-1), 1.5, COLORS['accent']),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                ('TOPPADDING', (0,0), (-1,-1), 4),
            ]))
        ]
    ]
    summary_table = Table(summary_data, colWidths=[310, 230])
    summary_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(KeepTogether(summary_table))
    
    story.append(Spacer(1, 40))
    thank_you_style = ParagraphStyle(
        'ThankYou', fontName=HEADING_FONT, fontSize=10,
        textColor=COLORS['accent'], alignment=TA_CENTER
    )
    story.append(Paragraph("Thank you for shopping with us! Please visit again.", thank_you_style))
    
    doc.build(story)
    return filepath

def total_body_style_right():
    return ParagraphStyle(
        'TotalBodyStyleRight', fontName=BODY_FONT, fontSize=9,
        textColor=COLORS['body'], alignment=TA_RIGHT
    )
