"""
Customer retention analytics and WhatsApp message generation.

Three responsibilities:
  1. Pattern detection  — find repeat purchases per customer and infer refill interval
  2. Reminder status    — flag schedules that are overdue or due soon
  3. Message generation — produce ready-to-send WhatsApp message text for
                          medication reminders and supplier reorder alerts
"""

from datetime import date, timedelta
from urllib.parse import quote
from sqlalchemy import func
from database import db, Customer, MedicationSchedule, Sale, SaleItem, Product
from forecasting import forecast_product, reorder_recommendation

PHARMACY_NAME = "Pharmacie Tramed"
PHARMACY_PHONE = "0788 301 960"
PHARMACY_ADDRESS = "KN 151 St, Kigali"


# ── Pattern detection ─────────────────────────────────────────────────────────

def detect_purchase_patterns(customer_id: int) -> list[dict]:
    """
    Analyse a customer's linked sales to find products bought repeatedly.
    Returns one entry per product with ≥2 purchases, sorted by purchase count.
    """
    rows = (
        db.session.query(
            Product,
            func.count(SaleItem.id).label("purchase_count"),
            func.min(func.date(Sale.created_at)).label("first_date"),
            func.max(func.date(Sale.created_at)).label("last_date"),
        )
        .join(SaleItem, SaleItem.product_id == Product.id)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(Sale.customer_id == customer_id)
        .group_by(Product.id)
        .having(func.count(SaleItem.id) >= 2)
        .order_by(func.count(SaleItem.id).desc())
        .all()
    )

    patterns = []
    for product, count, first_str, last_str in rows:
        first = date.fromisoformat(str(first_str))
        last  = date.fromisoformat(str(last_str))
        span  = (last - first).days
        avg_interval = round(span / (count - 1)) if count > 1 and span > 0 else None

        # Check whether this product is already scheduled
        already_scheduled = MedicationSchedule.query.filter_by(
            customer_id=customer_id,
            product_id=product.id,
            active=True,
        ).first()

        patterns.append({
            "product": product,
            "purchase_count": count,
            "first_date": first,
            "last_date": last,
            "avg_interval": avg_interval,
            "already_scheduled": already_scheduled is not None,
        })
    return patterns


# ── Reminder status ───────────────────────────────────────────────────────────

def _reminder_status(schedule: MedicationSchedule) -> dict:
    today = date.today()
    days_until = (schedule.next_reminder_date - today).days if schedule.next_reminder_date else None

    if days_until is None:
        urgency = "unknown"
    elif days_until < 0:
        urgency = "overdue"
    elif days_until == 0:
        urgency = "due_today"
    elif days_until <= 3:
        urgency = "due_soon"
    else:
        urgency = "upcoming"

    return {"days_until": days_until, "urgency": urgency}


def get_due_reminders(days_ahead: int = 7) -> list[dict]:
    """
    Return all active schedules due within `days_ahead` days,
    sorted by most overdue first.
    """
    cutoff = date.today() + timedelta(days=days_ahead)
    schedules = (
        MedicationSchedule.query
        .filter(
            MedicationSchedule.active == True,
            MedicationSchedule.next_reminder_date <= cutoff,
        )
        .order_by(MedicationSchedule.next_reminder_date.asc())
        .all()
    )
    results = []
    for sched in schedules:
        status = _reminder_status(sched)
        results.append({
            "schedule": sched,
            "customer": sched.customer,
            "product": sched.product,
            **status,
            "message": _reminder_message_text(sched, status["days_until"]),
            "whatsapp_url": _whatsapp_url(
                sched.customer.whatsapp_number,
                _reminder_message_text(sched, status["days_until"]),
            ),
        })
    return results


# ── Supplier reorder messages ──────────────────────────────────────────────────

def get_supplier_reorder_messages() -> list[dict]:
    """
    Group urgent/critical products by supplier and produce one reorder message
    per supplier.
    """
    from forecasting import all_product_forecasts
    results = all_product_forecasts()

    # Only include products that need reordering
    needs_order = [
        r for r in results
        if r["recommendation"]["urgency"] in ("critical", "urgent", "soon")
        and r["recommendation"]["reorder_qty"] > 0
    ]

    # Group by supplier
    by_supplier: dict[int, dict] = {}
    for r in needs_order:
        sup = r["product"].supplier
        if sup is None:
            continue
        if sup.id not in by_supplier:
            by_supplier[sup.id] = {"supplier": sup, "lines": []}
        by_supplier[sup.id]["lines"].append({
            "product": r["product"],
            "reorder_qty": r["recommendation"]["reorder_qty"],
            "urgency": r["recommendation"]["urgency"],
        })

    messages = []
    for sup_data in by_supplier.values():
        text = _supplier_order_text(sup_data["supplier"], sup_data["lines"])
        messages.append({
            "supplier": sup_data["supplier"],
            "lines": sup_data["lines"],
            "message": text,
            "whatsapp_url": _whatsapp_url(
                _to_wa_number(sup_data["supplier"].phone), text
            ),
        })
    return messages


# ── Message text generators ───────────────────────────────────────────────────

def _reminder_message_text(schedule: MedicationSchedule, days_until) -> str:
    customer = schedule.customer
    product  = schedule.product

    if days_until is not None and days_until < 0:
        timing = f"Your refill was due {abs(days_until)} day{'s' if abs(days_until) != 1 else ''} ago."
    elif days_until == 0:
        timing = "Your refill is due today."
    elif days_until is not None:
        timing = f"Your refill is coming up in {days_until} day{'s' if days_until != 1 else ''}."
    else:
        timing = "Your next refill is coming up."

    lines = [
        f"Hello {customer.name.split()[0]},",
        "",
        f"This is {PHARMACY_NAME} ({PHARMACY_ADDRESS}).",
        "",
        f"*{product.name}* — {timing}",
        f"You collect this every {schedule.interval_days} days.",
        "",
        "Please visit us or call to reserve your medication.",
        f"📞 {PHARMACY_PHONE}",
        "",
        "Thank you! 🙏",
    ]
    return "\n".join(lines)


def _supplier_order_text(supplier, items: list[dict]) -> str:
    lines = [
        f"Hello {supplier.name},",
        "",
        f"Please prepare the following order for {PHARMACY_NAME}:",
        "",
    ]
    for item in items:
        urgency_note = " ⚠️ URGENT" if item["urgency"] in ("critical", "urgent") else ""
        lines.append(f"• {item['product'].name}: *{item['reorder_qty']} units*{urgency_note}")

    lines += [
        "",
        f"Delivery to: {PHARMACY_ADDRESS}",
        f"Contact: {PHARMACY_PHONE}",
        "",
        "Thank you.",
    ]
    return "\n".join(lines)


def get_pharmacist_reorder_summary() -> dict:
    """
    Build a single reorder summary message addressed to the pharmacist themselves.
    Covers all critical / urgent / soon products in one WhatsApp message.
    Returns {"message": str, "whatsapp_url": str, "item_count": int}
    or None if nothing needs reordering.
    """
    from forecasting import all_product_forecasts
    from datetime import date

    results = all_product_forecasts()
    needs_order = [
        r for r in results
        if r["recommendation"]["urgency"] in ("critical", "urgent", "soon")
        and r["recommendation"]["reorder_qty"] > 0
    ]

    if not needs_order:
        return None

    today_str = date.today().strftime("%d %b %Y")
    lines = [
        f"*{PHARMACY_NAME} — Reorder Summary*",
        f"Week of {today_str}",
        "",
        "Items that need restocking:",
        "",
    ]

    urgency_labels = {"critical": "🔴 CRITICAL", "urgent": "🟠 URGENT", "soon": "🟡 SOON"}
    for r in needs_order:
        p = r["product"]
        rec = r["recommendation"]
        label = urgency_labels[rec["urgency"]]
        lines.append(
            f"{label} — {p.name}: order *{rec['reorder_qty']} units* "
            f"({rec['days_remaining']}d of stock left)"
        )

    lines += [
        "",
        f"Total: {len(needs_order)} product{'s' if len(needs_order) != 1 else ''} to reorder.",
        f"Check forecast: http://127.0.0.1:5000/forecast",
    ]

    msg = "\n".join(lines)
    return {
        "message": msg,
        "whatsapp_url": _whatsapp_url(_to_wa_number(PHARMACY_PHONE), msg),
        "item_count": len(needs_order),
    }


def _to_wa_number(phone: str) -> str:
    digits = "".join(filter(str.isdigit, phone))
    if digits.startswith("0"):
        digits = "250" + digits[1:]
    return digits


def _whatsapp_url(number: str, text: str) -> str:
    return f"https://wa.me/{number}?text={quote(text)}"
