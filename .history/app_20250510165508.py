# app.py
import os
import random
import smtplib
import redis
import json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from datetime import datetime, timedelta
from flask import Flask, render_template, request, send_file, jsonify
from reportlab.lib.pagesizes import letter
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
    Frame,
    PageTemplate,
    BaseDocTemplate
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
from reportlab.pdfgen import canvas
from dotenv import load_dotenv
import traceback
from io import BytesIO

load_dotenv()

app = Flask(__name__)

# Gmail configuration
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# Redis connection
redis_client = None

try:
    REDIS_URL = os.getenv("REDIS_URL")
    if not REDIS_URL:
        raise ValueError("REDIS_URL not found in environment variables")
    redis_client = redis.from_url(REDIS_URL)
    redis_client.ping()  # Test connection
    print("Successfully connected to Redis")
except Exception as e:
    print(f"Redis connection error: {e}")
    # Don't fail the app if Redis is not available, just log the error
    redis_client = None

# Global error handler
@app.errorhandler(Exception)
def handle_exception(e):
    traceback.print_exc()
    return jsonify({"status": "error", "message": f"Global error: {str(e)}"}), 500


def generate_invoice_number():
    return "K" + "".join(random.choices("0123456789", k=10))


def calculate_total(items):
    total = 0
    for item in items:
        total += float(item["quantity"]) * float(item["amount"])
    return total


class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        self.invoice_number = kwargs.pop('invoice_number', 'UNKNOWN')
        canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        """add info to each page (page numbers, etc)"""
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number()
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_number(self):
        self.saveState()
        self.setFont('Times-Roman', 9)
        self.drawString(inch, 0.75 * inch, f"Page {self.getPageNumber()} {self.invoice_number}")
        self.restoreState()


class OnePage(BaseDocTemplate):
    def __init__(self, filename, **kwargs):
        BaseDocTemplate.__init__(self, filename, **kwargs)
        self.addPageTemplates([PageTemplate(id='FirstPage', frames=Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id=None))])


def generate_pdf(invoice_data, logo_path=None, paid=False):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
    
    class PaidCanvas(NumberedCanvas):
        def showPage(self):
            if paid:
                # Add diagonal watermark
                self.saveState()
                self.setFont('Helvetica-Bold', 120)
                self.setFillColor(colors.Color(0, 0.7, 0, alpha=0.1))  # Light green with transparency
                self.translate(letter[0]/2, letter[1]/2)
                self.rotate(45)
                self.drawCentredString(0, 0, 'PAID')
                self.restoreState()
                
                # Add stamp in top-right corner
                self.saveState()
                self.setFont('Helvetica-Bold', 40)
                self.setFillColor(colors.Color(0, 0.7, 0, alpha=0.8))  # Darker green with less transparency
                self.drawString(letter[0]-200, letter[1]-100, 'PAID')
                self.restoreState()
            
            super().showPage()

    styles = getSampleStyleSheet()
    
    # Custom styles
    styles.add(ParagraphStyle(
        name='RightAlign',
        parent=styles['Normal'],
        alignment=TA_RIGHT
    ))
    
    story = []

    # Create logo image if path exists
    logo_img = None
    if logo_path:
        try:
            logo_img = Image(logo_path, width=110/72*inch, height=70/72*inch)
        except Exception as e:
            print(f"Error loading logo: {e}")
            logo_img = None

    # Header table with logo and company info
    header_data = [[
        Paragraph(
            f"<font size=24 color=red><b>{invoice_data['company_name']}</b></font>",
            styles["Normal"]
        ),
        logo_img if logo_img else Paragraph("", styles["Normal"])
    ]]
    header_table = Table(header_data, colWidths=[4.5*inch, 2.5*inch])
    header_table.setStyle(TableStyle([
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.3*inch))

    # Invoice details (number and date)
    invoice_details = [[
        Paragraph(
            f"<font size=14 color=red><b>INVOICE #{invoice_data['invoice_number']}</b></font>",
            styles["Normal"]
        ),
        Paragraph(
            f"<font size=12>Date: {invoice_data['date']}</font>",
            styles['RightAlign']
        )
    ]]
    details_table = Table(invoice_details, colWidths=[4.5*inch, 2.5*inch])
    details_table.setStyle(TableStyle([
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
    ]))
    story.append(details_table)
    story.append(Spacer(1, 0.3*inch))

    # Bill To section
    story.append(Paragraph("<font size=12><b>BILL TO:</b></font>", styles["Normal"]))
    story.append(Spacer(1, 0.1*inch))
    
    buyer_info_text = f"""
    <font size=11>
    {invoice_data['buyer_name']}<br/>
    {invoice_data['buyer_company']}<br/>
    Phone: {invoice_data['buyer_phone']}<br/>
    Email: {invoice_data['buyer_email']}
    </font>
    """
    story.append(Paragraph(buyer_info_text, styles["Normal"]))
    story.append(Spacer(1, 0.3*inch))

    # Items table
    items_data = [["QUANTITY", "DESCRIPTION", "UNIT PRICE", "AMOUNT"]]
    for item in invoice_data["items"]:
        unit_price = float(item["amount"])
        quantity = float(item["quantity"])
        amount = unit_price * quantity
        items_data.append([
            str(int(quantity)),
            item["description"],
            f"${unit_price:,.2f}",
            f"${amount:,.2f}"
        ])

    total = float(invoice_data["total"])
    
    # Create style for total row
    total_style = ParagraphStyle(
        'TotalStyle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        alignment=TA_RIGHT
    )

    # Add total row without HTML tags
    items_data.extend([
        ["", "", "", ""],
        ["", "", "TOTAL", f"${total:,.2f}"]
    ])

    items_table = Table(items_data, colWidths=[1*inch, 4*inch, 1*inch, 1*inch])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),
        ('ALIGN', (-2, 1), (-1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -2), 1, colors.black),
        ('LINEBELOW', (0, -2), (-1, -2), 1, colors.black),
        ('FONTNAME', (-2, -1), (-1, -1), 'Helvetica-Bold'),  # Bold font for total row
    ]))
    story.append(items_table)
    story.append(Spacer(1, 0.3*inch))

    # Payment terms and footer - only show if not paid
    if not paid:
        terms_text = """
        <font size=10>
        <b>PAYMENT TERMS</b><br/>
        You have 3 days from the date this invoice is issued to make a payment.<br/>
        Any late payment will result in a 50% increase based on the amount.<br/>
        All payments must be sent via Zelle to: 737-710-6090<br/><br/>
        All sales are final
        </font>
        """
        story.append(Paragraph(terms_text, styles["Normal"]))

    # Pass invoice_number to the canvas
    canvas_kwargs = {'invoice_number': invoice_data['invoice_number']}
    doc.build(story, canvasmaker=lambda *args, **kwargs: PaidCanvas(*args, **{**kwargs, **canvas_kwargs}))
    buffer.seek(0)
    return buffer


def send_email(recipients, company_name, invoice_number, pdf_buffer, is_paid=False):
    msg = MIMEMultipart()
    msg["From"] = EMAIL_ADDRESS
    
    # Handle various ways recipients might be provided
    if isinstance(recipients, str):
        cleaned_recipients = [r.strip() for r in recipients.split(',')]
    else:
        cleaned_recipients = [r.strip() for r in recipients]
        
    if not cleaned_recipients:
        print("No email recipients provided")
        return False
        
    msg["To"] = ", ".join(cleaned_recipients)
    
    if is_paid:
        subject = f"Payment Received - Invoice {invoice_number} from {company_name}"
        body = f"Thank you for your payment. Please find attached your paid invoice {invoice_number}."
    else:
        subject = f"{company_name} sent you an invoice due {(datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d')}"
        body = f"Please find attached invoice {invoice_number} from {company_name}."
    
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    # Attach PDF from buffer
    part = MIMEApplication(pdf_buffer.read(), _subtype="pdf")
    part.add_header("Content-Disposition", "attachment", filename=f"invoice_{invoice_number}.pdf")
    msg.attach(part)
    pdf_buffer.seek(0)  # Reset buffer position

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, cleaned_recipients, msg.as_string())
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False


def store_invoice(invoice_data):
    if redis_client:
        try:
            invoice_number = invoice_data['invoice_number']
            redis_client.set(f"invoice:{invoice_number}", json.dumps(invoice_data))
            return True
        except Exception as e:
            print(f"Error storing invoice: {e}")
    return False


def get_invoice(invoice_number):
    if redis_client:
        try:
            invoice_data = redis_client.get(f"invoice:{invoice_number}")
            return json.loads(invoice_data) if invoice_data else None
        except Exception as e:
            print(f"Error retrieving invoice: {e}")
    return None


@app.route("/lookup_invoice", methods=["POST"])
def lookup_invoice():
    try:
        invoice_number = request.form.get("invoice_number")
        if not invoice_number:
            return jsonify({"status": "error", "message": "Invoice number required"})
            
        invoice_data = get_invoice(invoice_number)
        if invoice_data:
            return jsonify({"status": "success", "data": invoice_data})
        return jsonify({"status": "error", "message": "Invoice not found"})
    except Exception as e:
        print(f"Lookup error: {e}")
        return jsonify({"status": "error", "message": str(e)})


@app.route("/search_invoices", methods=["POST"])
def search_invoices():
    try:
        partial_number = request.form.get("partial_number", "")
        if not partial_number:
            return jsonify({"status": "error", "message": "Number required"})
        
        # Search for matches in Redis
        matches = []
        pattern = f"invoice:K*{partial_number}*"
        
        if redis_client:
            for key in redis_client.scan_iter(pattern):
                invoice_data = redis_client.get(key)
                if invoice_data:
                    matches.append(json.loads(invoice_data))
        
        return jsonify({
            "status": "success",
            "matches": matches
        })
    except Exception as e:
        print(f"Search error: {e}")
        return jsonify({"status": "error", "message": str(e)})


@app.route("/", methods=["GET", "POST"])
def index():
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        try:
            company_name = request.form["company_name"]
            buyer_name = request.form["buyer_name"]
            buyer_company = request.form["buyer_company"]
            buyer_phone = request.form["buyer_phone"]
            buyer_email = request.form["buyer_email"]
            recipients = request.form.get("recipients", "")
            items = []
            i = 0
            while True:
                quantity = request.form.get(f"quantity[{i}]")
                description = request.form.get(f"description[{i}]")
                amount = request.form.get(f"amount[{i}]")
                if quantity is None or description is None or amount is None:
                    break
                items.append(
                    {"quantity": quantity, "description": description, "amount": amount}
                )
                i += 1

            invoice_number = generate_invoice_number()
            date = datetime.now().strftime("%Y-%m-%d")
            total = calculate_total(items)

            invoice_data = {
                "company_name": company_name,
                "buyer_name": buyer_name,
                "buyer_company": buyer_company,
                "buyer_phone": buyer_phone,
                "buyer_email": buyer_email,
                "invoice_number": invoice_number,
                "date": date,
                "items": items,
                "total": total,
            }

            # Store invoice in Redis
            store_invoice(invoice_data)

            # Handle logo upload
            logo_path = None
            if "logo" in request.files:
                logo = request.files["logo"]
                if logo.filename != "":
                    try:
                        # Ensure uploads directory exists
                        os.makedirs("uploads", exist_ok=True)
                        logo_path = os.path.join("uploads", logo.filename)
                        logo.save(logo_path)
                        print(f"Logo saved to {logo_path}")
                    except Exception as e:
                        print(f"Error saving logo: {e}")
                        # Continue without the logo if there's an error

            is_paid = "send_paid" in request.form
            pdf_buffer = generate_pdf(invoice_data, logo_path, paid=is_paid)
            
            try:
                email_sent = send_email(
                    recipients, company_name, invoice_number, pdf_buffer, is_paid=is_paid
                )
                if email_sent:
                    return jsonify({"status": "success"})
                else:
                    return jsonify({"status": "error", "message": "Failed to send email."})
            except Exception as email_err:
                traceback.print_exc()
                return jsonify({"status": "error", "message": f"Email sending error: {str(email_err)}"})

        except Exception as e:
            traceback.print_exc()
            return jsonify({"status": "error", "message": f"General error: {str(e)}"}), 500

    elif request.method == "POST":
        # Handle download
        try:
            company_name = request.form["company_name"]
            buyer_name = request.form["buyer_name"]
            buyer_company = request.form["buyer_company"]
            buyer_phone = request.form["buyer_phone"]
            buyer_email = request.form["buyer_email"]
            items = []
            i = 0
            while True:
                quantity = request.form.get(f"quantity[{i}]")
                description = request.form.get(f"description[{i}]")
                amount = request.form.get(f"amount[{i}]")
                if quantity is None or description is None or amount is None:
                    break
                items.append(
                    {"quantity": quantity, "description": description, "amount": amount}
                )
                i += 1

            invoice_number = generate_invoice_number()
            date = datetime.now().strftime("%Y-%m-%d")
            total = calculate_total(items)

            invoice_data = {
                "company_name": company_name,
                "buyer_name": buyer_name,
                "buyer_company": buyer_company,
                "buyer_phone": buyer_phone,
                "buyer_email": buyer_email,
                "invoice_number": invoice_number,
                "date": date,
                "items": items,
                "total": total,
            }

            # Store invoice in Redis
            store_invoice(invoice_data)

            # Handle logo upload
            logo_path = None
            if "logo" in request.files:
                logo = request.files["logo"]
                if logo.filename != "":
                    try:
                        # Ensure uploads directory exists
                        os.makedirs("uploads", exist_ok=True)
                        logo_path = os.path.join("uploads", logo.filename)
                        logo.save(logo_path)
                        print(f"Logo saved to {logo_path}")
                    except Exception as e:
                        print(f"Error saving logo: {e}")
                        # Continue without the logo if there's an error

            pdf_buffer = generate_pdf(invoice_data, logo_path)
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f"invoice_{invoice_number}.pdf"
            )
        except Exception as e:
            traceback.print_exc()
            return jsonify({"status": "error", "message": f"General error: {str(e)}"}), 500

    return render_template("index.html")


if __name__ == "__main__":
    # Ensure uploads directory exists
    os.makedirs("uploads", exist_ok=True)
    
    # Get port from environment variable for Railway deployment
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)