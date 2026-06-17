from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class RawSale(db.Model):
    """Flat import table — mirrors the Ishyiga Excel export exactly.
    Populated first; normalized tables are derived from this."""
    __tablename__ = "raw_sales"

    id               = db.Column(db.Integer, primary_key=True, autoincrement=True)
    id_invoice       = db.Column(db.Integer,  nullable=False, index=True)
    date             = db.Column(db.String(20))
    code             = db.Column(db.String(30))
    name_product     = db.Column(db.String(200))
    num_lot          = db.Column(db.String(50))
    quantite         = db.Column(db.Integer)
    price            = db.Column(db.Float)
    price_revient    = db.Column(db.Float)
    total            = db.Column(db.Float)
    tva              = db.Column(db.Float,  default=0)
    employe          = db.Column(db.String(100))
    num_affiliation  = db.Column(db.String(50))
    numero_quittance = db.Column(db.String(50))
    nom_client       = db.Column(db.String(100))
    prenom_client    = db.Column(db.String(100))
    percentage       = db.Column(db.Float,  default=0)
    time             = db.Column(db.String(20))
    type_paiement    = db.Column(db.String(30))
    monnaie          = db.Column(db.Float,  default=0)


class Supplier(db.Model):
    __tablename__ = "suppliers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    products = db.relationship("Product", backref="supplier", lazy=True)


class Customer(db.Model):
    __tablename__ = "customers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.String(300))
    sales = db.relationship("Sale", backref="customer", lazy=True)
    schedules = db.relationship("MedicationSchedule", backref="customer", lazy=True)
    loyalty = db.relationship("LoyaltyAccount", backref="customer", uselist=False, lazy=True)

    @property
    def whatsapp_number(self):
        """Convert 07XXXXXXXX to 250XXXXXXXXX for wa.me links."""
        digits = "".join(filter(str.isdigit, self.phone))
        if digits.startswith("0"):
            digits = "250" + digits[1:]
        return digits


class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=True, index=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(80), nullable=False, default="General")
    unit_price = db.Column(db.Float, nullable=False)
    cost_price = db.Column(db.Float, nullable=False)
    stock_quantity = db.Column(db.Integer, default=0)
    min_stock_level = db.Column(db.Integer, default=10)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"))
    sale_items = db.relationship("SaleItem", backref="product", lazy=True)
    schedules = db.relationship("MedicationSchedule", backref="product", lazy=True)

    @property
    def is_low_stock(self):
        return self.stock_quantity <= self.min_stock_level

    @property
    def margin_percent(self):
        if self.cost_price == 0:
            return 0
        return round(((self.unit_price - self.cost_price) / self.unit_price) * 100, 1)


class Sale(db.Model):
    __tablename__ = "sales"
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    total_amount = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(30), default="cash")
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=True)
    items = db.relationship("SaleItem", backref="sale", lazy=True)


class SaleItem(db.Model):
    __tablename__ = "sale_items"
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sales.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)


class LoyaltyAccount(db.Model):
    __tablename__ = "loyalty_accounts"
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), unique=True, nullable=False)
    points_balance = db.Column(db.Integer, default=0)    # spendable right now
    lifetime_points = db.Column(db.Integer, default=0)   # never decreases — controls tier
    tier = db.Column(db.String(20), default="bronze")    # bronze / silver / gold
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    transactions = db.relationship("LoyaltyTransaction", backref="account", lazy=True)


class LoyaltyTransaction(db.Model):
    __tablename__ = "loyalty_transactions"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("loyalty_accounts.id"), nullable=False)
    points = db.Column(db.Integer, nullable=False)        # positive = earn, negative = redeem
    transaction_type = db.Column(db.String(20), nullable=False)  # earn / redeem / manual
    sale_id = db.Column(db.Integer, db.ForeignKey("sales.id"), nullable=True)
    note = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class MedicationSchedule(db.Model):
    __tablename__ = "medication_schedules"
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    interval_days = db.Column(db.Integer, nullable=False, default=30)
    last_purchase_date = db.Column(db.Date, nullable=True)
    next_reminder_date = db.Column(db.Date, nullable=True)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.String(200))

