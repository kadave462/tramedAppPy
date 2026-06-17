"""Populate the DB with realistic Pharmacie Tramed mock data."""
import random
from datetime import datetime, timedelta, date
from database import db, Supplier, Product, Sale, SaleItem, Customer, MedicationSchedule, LoyaltyAccount, LoyaltyTransaction


SUPPLIERS = [
    {"name": "Labophar Rwanda",      "phone": "0788 100 200", "email": "orders@labophar.rw"},
    {"name": "Cipla Quality Chemical","phone": "0788 300 400", "email": "rw@cipla.com"},
    {"name": "Strides Pharma",        "phone": "0788 500 600", "email": "kigali@strides.com"},
    {"name": "Giga Med Suppliers",    "phone": "0788 700 800", "email": "info@gigamed.rw"},
]

PRODUCTS = [
    # (name, category, sell_price, cost_price, stock, min_stock)
    ("Paracetamol 500mg (strip/10)",          "Analgesic",       500,  280, 120, 20),
    ("Ibuprofen 400mg (strip/10)",            "Analgesic",       800,  450,  85, 20),
    ("Amoxicillin 500mg (strip/12)",          "Antibiotic",     2500, 1400,  45, 15),
    ("Metronidazole 400mg (strip/10)",        "Antibiotic",     1200,  700,  60, 15),
    ("Ciprofloxacin 500mg (strip/10)",        "Antibiotic",     3000, 1700,   8, 15),
    ("Artemether/Lumefantrine 20/120mg",      "Antimalarial",   4500, 2600,  55, 20),
    ("Artesunate 200mg (strip/3)",            "Antimalarial",   5000, 2900,  30, 15),
    ("ORS Sachet (x10)",                      "Rehydration",    1500,  800,  70, 25),
    ("Zinc Sulphate 20mg (strip/10)",         "Supplement",     1000,  550,  40, 20),
    ("Vitamin C 500mg (strip/10)",            "Supplement",      600,  320,   6, 20),
    ("Folic Acid 5mg (strip/10)",             "Supplement",      400,  200,  90, 20),
    ("Metformin 500mg (strip/30)",            "Diabetes",       1800,  950,  35, 15),
    ("Glibenclamide 5mg (strip/30)",          "Diabetes",       1500,  800,  20, 15),
    ("Amlodipine 5mg (strip/30)",             "Cardiovascular", 2000, 1100,  25, 15),
    ("Enalapril 10mg (strip/30)",             "Cardiovascular", 2200, 1200,   7, 15),
    ("Atorvastatin 20mg (strip/30)",          "Cardiovascular", 3500, 1900,  18, 10),
    ("Omeprazole 20mg (strip/14)",            "Gastro",         1800, 1000,  50, 20),
    ("Ranitidine 150mg (strip/10)",           "Gastro",          900,  500,  65, 20),
    ("Cotrimoxazole 480mg (strip/14)",        "Antibiotic",     1000,  550,  55, 20),
    ("Doxycycline 100mg (strip/10)",          "Antibiotic",     1500,  800,  12, 15),
    ("Chloroquine 250mg (strip/10)",          "Antimalarial",   1200,  650,  40, 15),
    ("Prednisolone 5mg (strip/30)",           "Steroid",        1600,  850,  30, 10),
    ("Salbutamol Inhaler 100mcg",             "Respiratory",    6000, 3400,   9, 10),
    ("Cetirizine 10mg (strip/10)",            "Antihistamine",   700,  380,  75, 20),
    ("Loratadine 10mg (strip/10)",            "Antihistamine",   800,  430,  60, 20),
    ("Diclofenac 50mg (strip/10)",            "Analgesic",       900,  500,  48, 20),
    ("Surgical Gloves (box/100)",             "Medical Supply", 8000, 5000,   4,  5),
    ("Face Masks (box/50)",                   "Medical Supply", 3000, 1800,  15, 10),
    ("Alcohol 70% 500ml",                     "Antiseptic",     1500,  800,  22, 10),
    ("Bandage 10cm x 5m",                     "Medical Supply", 1200,  700,  18, 10),
]

PAYMENT_METHODS = ["cash", "cash", "cash", "momo", "momo", "card"]

# Chronic customers: (name, phone, notes, [(product_index, interval_days, last_purchase_days_ago)])
CHRONIC_CUSTOMERS = [
    ("Uwimana Jean",      "0788 123 456", "Type 2 diabetes",
     [(11, 30, 36), (12, 30, 36)]),                           # Metformin + Glibenclamide, OVERDUE
    ("Mukamana Alice",    "0788 234 567", "Hypertension",
     [(13, 30, 28)]),                                          # Amlodipine, DUE SOON
    ("Habimana Pierre",   "0788 345 678", "Asthma",
     [(22, 60, 55)]),                                          # Salbutamol, DUE SOON
    ("Bizimana Emmanuel", "0789 456 789", "Cardiovascular",
     [(15, 30, 33), (14, 30, 33)]),                            # Atorvastatin + Enalapril, OVERDUE
    ("Uwera Diane",       "0789 567 890", "Type 2 diabetes",
     [(11, 30, 24)]),                                          # Metformin, upcoming
    ("Nkurunziza Robert", "0789 678 901", "Walk-in customer",
     []),
    ("Ingabire Celine",   "0789 789 012", "Seasonal allergies",
     []),
    ("Kamanzi David",     "0788 890 123", "New customer",
     []),
]


def _add_sale(db_session, customer_id, product, qty, sale_date, method="cash"):
    sale = Sale(
        created_at=sale_date,
        total_amount=qty * product.unit_price,
        payment_method=method,
        customer_id=customer_id,
    )
    db_session.add(sale)
    db_session.flush()
    item = SaleItem(sale_id=sale.id, product_id=product.id,
                    quantity=qty, unit_price=product.unit_price)
    db_session.add(item)
    return sale


def seed(app):
    with app.app_context():
        db.drop_all()
        db.create_all()

        # ── Suppliers ────────────────────────────────────────────────────────
        suppliers = []
        for s in SUPPLIERS:
            sup = Supplier(**s)
            db.session.add(sup)
            suppliers.append(sup)
        db.session.flush()

        # ── Products ─────────────────────────────────────────────────────────
        products = []
        for i, (name, cat, sell, cost, stock, min_s) in enumerate(PRODUCTS):
            sup = suppliers[i % len(suppliers)]
            p = Product(name=name, category=cat, unit_price=sell, cost_price=cost,
                        stock_quantity=stock, min_stock_level=min_s, supplier_id=sup.id)
            db.session.add(p)
            products.append(p)
        db.session.flush()

        # ── Anonymous sales — 90 days of history ────────────────────────────
        random.seed(42)
        today_dt = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        for day_offset in range(89, -1, -1):
            sale_date = today_dt - timedelta(days=day_offset)
            base = 8
            if sale_date.weekday() >= 5:
                base = 11
            if sale_date.day in (1, 2, 3, 29, 30, 31):
                base += 2
            n_sales = random.randint(base - 2, base + 4)
            for _ in range(n_sales):
                hour = random.randint(8, 19)
                minute = random.randint(0, 59)
                sale_dt = sale_date.replace(hour=hour, minute=minute)
                n_items = random.randint(1, 4)
                chosen = random.sample(products, n_items)
                total = 0
                sale = Sale(created_at=sale_dt, total_amount=0,
                            payment_method=random.choice(PAYMENT_METHODS))
                db.session.add(sale)
                db.session.flush()
                for prod in chosen:
                    qty = random.randint(1, 3)
                    item = SaleItem(sale_id=sale.id, product_id=prod.id,
                                    quantity=qty, unit_price=prod.unit_price)
                    total += qty * prod.unit_price
                    db.session.add(item)
                sale.total_amount = total

        # ── Chronic customers + repeat purchase history ──────────────────────
        for name, phone, notes, schedules in CHRONIC_CUSTOMERS:
            cust = Customer(name=name, phone=phone, notes=notes)
            db.session.add(cust)
            db.session.flush()

            for prod_idx, interval, last_days_ago in schedules:
                prod = products[prod_idx]

                # Create 3 historical purchases at ~interval spacing
                last_purchase_dt = today_dt - timedelta(days=last_days_ago)
                purchase_dates = [
                    last_purchase_dt,
                    last_purchase_dt - timedelta(days=interval + random.randint(-2, 2)),
                    last_purchase_dt - timedelta(days=2 * interval + random.randint(-3, 3)),
                ]
                for pd in purchase_dates:
                    if pd < today_dt - timedelta(days=89):
                        continue
                    sale_dt = pd.replace(hour=random.randint(9, 17), minute=random.randint(0, 59))
                    _add_sale(db.session, cust.id, prod, 1, sale_dt,
                              random.choice(PAYMENT_METHODS))

                # Create the medication schedule
                last_date = last_purchase_dt.date()
                next_reminder = last_date + timedelta(days=interval - 3)
                sched = MedicationSchedule(
                    customer_id=cust.id,
                    product_id=prod.id,
                    interval_days=interval,
                    last_purchase_date=last_date,
                    next_reminder_date=next_reminder,
                    active=True,
                )
                db.session.add(sched)

        # ── Loyalty accounts for chronic customers ───────────────────────────
        # Award retroactive points based on each customer's linked sales
        for cust in Customer.query.all():
            linked_sales = Sale.query.filter_by(customer_id=cust.id).all()
            total_rwf = sum(s.total_amount for s in linked_sales)
            if total_rwf < 1000:
                continue
            base_pts = int(total_rwf / 100)

            # Determine tier from lifetime points
            tier = "bronze"
            if base_pts >= 2000:
                tier = "gold"
            elif base_pts >= 500:
                tier = "silver"
            # Apply tier multiplier
            multiplier = {"bronze": 1.0, "silver": 1.5, "gold": 2.0}[tier]
            pts = int(base_pts * multiplier)

            acct = LoyaltyAccount(
                customer_id=cust.id,
                points_balance=pts,
                lifetime_points=pts,
                tier=tier,
            )
            db.session.add(acct)
            db.session.flush()
            db.session.add(LoyaltyTransaction(
                account_id=acct.id, points=pts,
                transaction_type="earn",
                note="Amanota yo gutangira (retroactive)",
            ))

        db.session.commit()
        print("Database seeded successfully.")
