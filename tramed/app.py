import os
from flask import Flask, render_template, jsonify, request, g
from sqlalchemy import func, desc
from datetime import datetime, timedelta
from database import db, Product, Sale, SaleItem, Supplier, Customer, MedicationSchedule, LoyaltyAccount
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///tramed.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SCHEDULER_API_ENABLED"] = False
db.init_app(app)


@app.context_processor
def inject_now():
    return {"now": datetime.utcnow()}


# ── Helpers ──────────────────────────────────────────────────────────────────

def fmt_rwf(amount):
    return f"{int(amount):,} RWF"


def sales_in_range(start, end):
    return Sale.query.filter(Sale.created_at >= start, Sale.created_at < end).all()


def revenue_in_range(start, end):
    result = db.session.query(func.sum(Sale.total_amount)).filter(
        Sale.created_at >= start, Sale.created_at < end
    ).scalar()
    return result or 0


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    week_start = today - timedelta(days=7)
    month_start = today.replace(day=1)

    today_rev = revenue_in_range(today, today + timedelta(days=1))
    yesterday_rev = revenue_in_range(yesterday, today)
    week_rev = revenue_in_range(week_start, today + timedelta(days=1))
    month_rev = revenue_in_range(month_start, today + timedelta(days=1))

    today_sales = len(sales_in_range(today, today + timedelta(days=1)))

    rev_change = 0
    if yesterday_rev > 0:
        rev_change = round(((today_rev - yesterday_rev) / yesterday_rev) * 100, 1)

    low_stock = Product.query.filter(
        Product.stock_quantity <= Product.min_stock_level
    ).order_by(Product.stock_quantity.asc()).all()

    # Top 5 products by revenue (last 30 days)
    thirty_ago = today - timedelta(days=30)
    top_products = db.session.query(
        Product.name,
        func.sum(SaleItem.quantity * SaleItem.unit_price).label("revenue"),
        func.sum(SaleItem.quantity).label("units")
    ).join(SaleItem).join(Sale).filter(
        Sale.created_at >= thirty_ago
    ).group_by(Product.id).order_by(desc("revenue")).limit(5).all()

    return render_template("dashboard.html",
        today_rev=today_rev,
        yesterday_rev=yesterday_rev,
        week_rev=week_rev,
        month_rev=month_rev,
        today_sales=today_sales,
        rev_change=rev_change,
        low_stock=low_stock,
        top_products=top_products,
        fmt=fmt_rwf,
    )


@app.route("/inventory")
def inventory():
    category = request.args.get("category", "")
    search = request.args.get("search", "")
    q = Product.query
    if category:
        q = q.filter(Product.category == category)
    if search:
        q = q.filter(Product.name.ilike(f"%{search}%"))
    products = q.order_by(Product.category, Product.name).all()
    categories = db.session.query(Product.category).distinct().order_by(Product.category).all()
    categories = [c[0] for c in categories]
    return render_template("inventory.html", products=products, categories=categories,
                           selected_category=category, search=search)


@app.route("/sales")
def sales():
    page = request.args.get("page", 1, type=int)
    per_page = 25
    sales_page = Sale.query.order_by(Sale.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return render_template("sales.html", sales=sales_page)


# ── JSON API for charts ───────────────────────────────────────────────────────

@app.route("/api/revenue-chart")
def api_revenue_chart():
    days = int(request.args.get("days", 30))
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    labels, values = [], []
    for i in range(days - 1, -1, -1):
        day = today - timedelta(days=i)
        rev = revenue_in_range(day, day + timedelta(days=1))
        labels.append(day.strftime("%d %b"))
        values.append(round(rev))
    return jsonify({"labels": labels, "values": values})


@app.route("/api/category-chart")
def api_category_chart():
    thirty_ago = datetime.utcnow() - timedelta(days=30)
    rows = db.session.query(
        Product.category,
        func.sum(SaleItem.quantity * SaleItem.unit_price).label("revenue")
    ).join(SaleItem).join(Sale).filter(
        Sale.created_at >= thirty_ago
    ).group_by(Product.category).order_by(desc("revenue")).all()
    return jsonify({
        "labels": [r[0] for r in rows],
        "values": [round(r[1]) for r in rows]
    })


@app.route("/forecast")
def forecast():
    from forecasting import all_product_forecasts
    from retention import get_supplier_reorder_messages, get_pharmacist_reorder_summary
    results = all_product_forecasts()
    counts = {"critical": 0, "urgent": 0, "soon": 0, "ok": 0}
    for r in results:
        counts[r["recommendation"]["urgency"]] += 1
    supplier_msgs = get_supplier_reorder_messages()
    pharmacist_summary = get_pharmacist_reorder_summary()
    return render_template("forecast.html", results=results, counts=counts,
                           fmt=fmt_rwf, supplier_msgs=supplier_msgs,
                           pharmacist_summary=pharmacist_summary)


@app.route("/api/product-forecast/<int:product_id>")
def api_product_forecast(product_id):
    from forecasting import forecast_product
    fc = forecast_product(product_id, horizon=30)
    return jsonify(fc)


@app.route("/customers")
def customers():
    q = request.args.get("q", "").strip()
    query = Customer.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(Customer.name.ilike(like), Customer.phone.ilike(like))
        )
    customers = query.order_by(Customer.name).all()
    products = Product.query.order_by(Product.name).all()
    from retention import get_due_reminders
    due = get_due_reminders(days_ahead=7)
    due_customer_ids = {r["customer"].id for r in due}
    return render_template("customers.html", customers=customers,
                           products=products, due_customer_ids=due_customer_ids, q=q)


@app.route("/customers/new", methods=["POST"])
def customer_new():
    name  = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    notes = request.form.get("notes", "").strip()
    if name and phone:
        c = Customer(name=name, phone=phone, notes=notes)
        db.session.add(c)
        db.session.commit()
    return _redirect("/customers")


@app.route("/customers/<int:customer_id>")
def customer_detail(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    from retention import detect_purchase_patterns
    patterns = detect_purchase_patterns(customer_id)
    products = Product.query.order_by(Product.name).all()
    sales = Sale.query.filter_by(customer_id=customer_id).order_by(Sale.created_at.desc()).all()
    from datetime import datetime
    return render_template("customer_detail.html", customer=customer,
                           patterns=patterns, products=products, sales=sales,
                           today=datetime.now())


@app.route("/customers/<int:customer_id>/schedule/add", methods=["POST"])
def schedule_add(customer_id):
    Customer.query.get_or_404(customer_id)
    from datetime import date, timedelta
    product_id    = int(request.form["product_id"])
    interval_days = int(request.form["interval_days"])
    last_date_str = request.form.get("last_purchase_date", "")
    notes         = request.form.get("notes", "").strip()
    last_date = date.fromisoformat(last_date_str) if last_date_str else date.today()
    next_reminder = last_date + timedelta(days=interval_days - 3)
    sched = MedicationSchedule(
        customer_id=customer_id, product_id=product_id,
        interval_days=interval_days, last_purchase_date=last_date,
        next_reminder_date=next_reminder, active=True, notes=notes,
    )
    db.session.add(sched)
    db.session.commit()
    return _redirect(f"/customers/{customer_id}")


@app.route("/customers/<int:customer_id>/schedule/<int:sched_id>/toggle", methods=["POST"])
def schedule_toggle(customer_id, sched_id):
    sched = MedicationSchedule.query.get_or_404(sched_id)
    sched.active = not sched.active
    db.session.commit()
    return _redirect(f"/customers/{customer_id}")


@app.route("/customers/<int:customer_id>/schedule/<int:sched_id>/renew", methods=["POST"])
def schedule_renew(customer_id, sched_id):
    from datetime import date, timedelta
    sched = MedicationSchedule.query.get_or_404(sched_id)
    sched.last_purchase_date = date.today()
    sched.next_reminder_date = date.today() + timedelta(days=sched.interval_days - 3)
    db.session.commit()
    return _redirect(f"/customers/{customer_id}")


@app.route("/portal", methods=["GET", "POST"])
def portal_lookup():
    error = None
    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        digits = "".join(filter(str.isdigit, phone))
        customer = Customer.query.filter(Customer.phone.ilike(f"%{phone}%")).first()
        if not customer and len(digits) >= 7:
            customer = Customer.query.filter(Customer.phone.ilike(f"%{digits[-9:]}%")).first()
        if customer:
            return _redirect(f"/portal/{customer.id}")
        error = "No account found for that number. Please check and try again."
    return render_template("portal_lookup.html", error=error)


@app.route("/portal/<int:customer_id>")
def portal(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    sales = Sale.query.filter_by(customer_id=customer_id).order_by(Sale.created_at.desc()).all()
    today = datetime.utcnow().date()
    return render_template("portal.html", customer=customer, sales=sales,
                           loyalty=customer.loyalty, today=today)


@app.route("/portal/<int:customer_id>/shop/<int:product_id>")
def portal_shop(customer_id, product_id):
    from urllib.parse import quote
    customer = Customer.query.get_or_404(customer_id)
    product = Product.query.get_or_404(product_id)
    PHARMACY_WHATSAPP = "250788301960"
    msg = (
        f"Hello Pharmacie Tramed, I'd like to refill my {product.name}. "
        f"My name is {customer.name}. Please let me know when it's ready. Thank you."
    )
    wa_url = f"https://wa.me/{PHARMACY_WHATSAPP}?text={quote(msg)}"
    return render_template("portal_shop.html", customer=customer, product=product, wa_url=wa_url)


@app.route("/messages")
def messages():
    from retention import get_due_reminders, get_supplier_reorder_messages
    reminders = get_due_reminders(days_ahead=7)
    supplier_msgs = get_supplier_reorder_messages()
    return render_template("messages.html", reminders=reminders, supplier_msgs=supplier_msgs)


def _redirect(url):
    from flask import redirect
    return redirect(url)


@app.route("/loyalty")
def loyalty():
    from loyalty import loyalty_summary, TIERS, points_to_rwf
    summary = loyalty_summary()
    all_accounts = (LoyaltyAccount.query
                    .order_by(LoyaltyAccount.lifetime_points.desc()).all())
    return render_template("loyalty.html", **summary, all_accounts=all_accounts)


@app.route("/loyalty/counter")
def loyalty_counter():
    return render_template("loyalty_counter.html")


@app.route("/api/loyalty/lookup")
def api_loyalty_lookup():
    from loyalty import get_or_create_account, points_to_rwf, TIERS
    phone = request.args.get("phone", "").strip()
    if not phone:
        return jsonify({"error": "Phone required"}), 400
    digits = "".join(filter(str.isdigit, phone))
    customer = Customer.query.filter(
        Customer.phone.like(f"%{digits[-7:]}%")
    ).first()
    if not customer:
        return jsonify({"found": False})
    acct = customer.loyalty
    if not acct:
        acct = get_or_create_account(customer.id)
        db.session.commit()
    tier = TIERS[acct.tier]
    return jsonify({
        "found": True,
        "customer_id": customer.id,
        "name": customer.name,
        "phone": customer.phone,
        "tier": acct.tier,
        "tier_label": tier["label"],
        "points_balance": acct.points_balance,
        "lifetime_points": acct.lifetime_points,
        "rwf_value": points_to_rwf(acct.points_balance),
        "next_at": tier["next_at"],
        "pts_to_next": (tier["next_at"] - acct.lifetime_points) if tier["next_at"] else None,
    })


@app.route("/api/loyalty/award", methods=["POST"])
def api_loyalty_award():
    from loyalty import award_points
    data = request.get_json()
    result = award_points(
        customer_id=int(data["customer_id"]),
        amount_rwf=float(data["amount_rwf"]),
    )
    if result is None:
        return jsonify({"ok": False,
                        "reason": f"Minimum purchase is 1,000 RWF to earn points"}), 400
    db.session.commit()
    return jsonify({
        "ok": True,
        "points_earned": result["points_earned"],
        "new_balance": result["new_balance"],
        "tier": result["tier"],
        "tier_label": result["tier_label"],
        "tier_upgraded": result["tier_upgraded"],
        "rwf_value": result["rwf_value"],
        "message": result["message"],
        "whatsapp_url": result["whatsapp_url"],
    })


@app.route("/api/loyalty/redeem", methods=["POST"])
def api_loyalty_redeem():
    from loyalty import redeem_points
    data = request.get_json()
    result = redeem_points(
        customer_id=int(data["customer_id"]),
        points_to_use=int(data["points"]),
        sale_amount=float(data["sale_amount"]),
    )
    if result is None:
        return jsonify({"ok": False, "reason": "Invalid redemption request"}), 400
    db.session.commit()
    return jsonify({"ok": True, **result})


@app.route("/shop")
def shop():
    from chat import PHARMACY_WHATSAPP
    category = request.args.get("category", "")
    search = request.args.get("q", "")
    q = Product.query
    if category:
        q = q.filter(Product.category == category)
    if search:
        q = q.filter(Product.name.ilike(f"%{search}%"))
    products = q.order_by(Product.category, Product.name).all()
    categories = db.session.query(Product.category).distinct().order_by(Product.category).all()
    categories = [c[0] for c in categories]
    return render_template("shop.html", products=products, categories=categories,
                           selected_category=category, search=search,
                           pharmacy_whatsapp=PHARMACY_WHATSAPP)


@app.route("/api/chat", methods=["POST"])
def api_chat():
    from chat import chat as chat_fn
    data = request.get_json()
    messages = data.get("messages", [])
    if not messages:
        return jsonify({"error": "No messages"}), 400
    try:
        reply = chat_fn(messages)
        return jsonify({"reply": reply})
    except ValueError as e:
        return jsonify({"error": str(e)}), 503
    except Exception:
        return jsonify({"error": "Chat unavailable"}), 503


@app.route("/api/stock-update", methods=["POST"])
def api_stock_update():
    data = request.get_json()
    product = Product.query.get_or_404(data["id"])
    product.stock_quantity = int(data["quantity"])
    db.session.commit()
    return jsonify({"ok": True, "new_quantity": product.stock_quantity})


# ── Education ─────────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTES_DIR = os.path.join(BASE_DIR, "notes")
EDU_DIR   = os.path.join(BASE_DIR, "educational materials", "Phase 1 plan")

NOTES_META = {
    "Project Build Notes.html":          {"title": "Project Build Notes",        "desc": "Overview of the tech stack, architecture, and project structure."},
    "notes.html":                         {"title": "Implementation Notes",       "desc": "Detailed implementation notes covering all modules and decisions."},
    "forecasting-module.html":            {"title": "Forecasting Module",         "desc": "Demand forecasting logic: linear trend, seasonality, and reorder rules."},
    "customer-retention-module.html":     {"title": "Customer Retention Module",  "desc": "Refill schedule detection, reminder logic, and WhatsApp flows."},
    "customer-loyalty-module.html":       {"title": "Loyalty Module",             "desc": "Points system, tier mechanics, and Kinyarwanda messaging design."},
    "automation.html":                    {"title": "Automation & WhatsApp",      "desc": "Twilio setup, APScheduler weekly jobs, and wa.me deep-link patterns."},
    "portal.html":                        {"title": "Customer Portal",            "desc": "Public-facing portal design: lookup, loyalty view, and shop flow."},
}

@app.route("/education")
def education():
    from flask import send_from_directory
    notes = []
    for filename, meta in NOTES_META.items():
        notes.append({"filename": filename, **meta})
    return render_template("education.html", notes=notes)


@app.route("/education/notes/<path:filename>")
def education_note(filename):
    from flask import send_from_directory, abort
    safe = os.path.basename(filename)
    if safe not in NOTES_META:
        abort(404)
    return send_from_directory(NOTES_DIR, safe)


@app.route("/education/files/<path:filename>")
def education_file(filename):
    from flask import send_from_directory, abort
    allowed = {"tramed_brief_clean.pdf", "sales of 13_05.xlsx"}
    safe = os.path.basename(filename)
    if safe not in allowed:
        abort(404)
    return send_from_directory(EDU_DIR, safe, as_attachment=(safe.endswith(".xlsx")))


# ── Scheduler ────────────────────────────────────────────────────────────────

from flask_apscheduler import APScheduler

scheduler = APScheduler()

@scheduler.task("cron", id="weekly_reorder_summary", day_of_week="mon", hour=8, minute=0)
def weekly_reorder_summary():
    """Runs every Monday at 08:00 — sends the pharmacist a reorder summary."""
    with app.app_context():
        from retention import get_pharmacist_reorder_summary
        from notifier import send_whatsapp
        summary = get_pharmacist_reorder_summary()
        if summary:
            to = os.getenv("PHARMACIST_WHATSAPP", "")
            send_whatsapp(to, summary["message"])
        else:
            import logging
            logging.getLogger(__name__).info("[scheduler] Weekly check: all stock OK, no message sent.")


# ── Init ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db_path = os.path.join(app.instance_path, "tramed.db")
    with app.app_context():
        if not os.path.exists(db_path):
            os.makedirs(app.instance_path, exist_ok=True)
            db.create_all()
            from seed_data import seed
            seed(app)
    scheduler.init_app(app)
    scheduler.start()
    app.run(debug=True, port=5000, use_reloader=False)
