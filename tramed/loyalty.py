"""
Customer Loyalty System — Pharmacie Tramed

Rules:
  - Minimum purchase: 1,000 RWF to earn points
  - Base rate: 1 point per 100 RWF spent
  - Tier multipliers applied on top of base rate
  - Tier is based on LIFETIME points (never resets after redemption)
  - Redemption: 100 points = 500 RWF discount
  - Max redemption per sale: 50% of sale value

Tiers:
  Bronze   0  – 499  pts  ×1.0
  Silver   500 – 1999 pts  ×1.5
  Gold     2000+      pts  ×2.0
"""

from urllib.parse import quote
from sqlalchemy import func
from database import db, LoyaltyAccount, LoyaltyTransaction, Customer

# ── Constants ─────────────────────────────────────────────────────────────────

MIN_PURCHASE_RWF   = 1_000
REDEMPTION_VALUE   = 500    # RWF per 100 points redeemed
MAX_REDEEM_PCT     = 0.50   # max 50% of sale value

TIERS = {
    "bronze": {"min": 0,    "multiplier": 1.0, "label": "Bronze 🥉", "next": "silver", "next_at": 500},
    "silver": {"min": 500,  "multiplier": 1.5, "label": "Silver 🥈", "next": "gold",   "next_at": 2000},
    "gold":   {"min": 2000, "multiplier": 2.0, "label": "Gold 🥇",   "next": None,     "next_at": None},
}

PHARMACY_NAME  = "Pharmacie Tramed"
PHARMACY_PHONE = "0788 301 960"


# ── Core calculations ─────────────────────────────────────────────────────────

def calculate_tier(lifetime_pts: int) -> str:
    if lifetime_pts >= 2000:
        return "gold"
    if lifetime_pts >= 500:
        return "silver"
    return "bronze"


def points_for_amount(amount_rwf: float, tier: str) -> int:
    """Points earned for a given spend amount and current tier."""
    if amount_rwf < MIN_PURCHASE_RWF:
        return 0
    base = int(amount_rwf / 100)
    return int(base * TIERS[tier]["multiplier"])


def points_to_rwf(points: int) -> int:
    """How much discount (RWF) a points balance is worth."""
    return (points // 100) * REDEMPTION_VALUE


# ── Account management ────────────────────────────────────────────────────────

def get_or_create_account(customer_id: int) -> LoyaltyAccount:
    acct = LoyaltyAccount.query.filter_by(customer_id=customer_id).first()
    if not acct:
        acct = LoyaltyAccount(customer_id=customer_id,
                               points_balance=0, lifetime_points=0, tier="bronze")
        db.session.add(acct)
        db.session.flush()
    return acct


def award_points(customer_id: int, amount_rwf: float,
                 sale_id: int = None, note: str = "") -> dict | None:
    """
    Award points for a purchase.
    Returns a result dict (including Kinyarwanda WhatsApp message) or None
    if amount is below the minimum threshold.
    Caller must call db.session.commit() after.
    """
    acct = get_or_create_account(customer_id)
    pts  = points_for_amount(amount_rwf, acct.tier)
    if pts == 0:
        return None

    old_tier = acct.tier
    acct.points_balance  += pts
    acct.lifetime_points += pts
    acct.tier = calculate_tier(acct.lifetime_points)
    tier_upgraded = acct.tier != old_tier

    db.session.add(LoyaltyTransaction(
        account_id=acct.id, points=pts, transaction_type="earn",
        sale_id=sale_id,
        note=note or f"Kugura: {int(amount_rwf):,} RWF",
    ))
    db.session.flush()

    msg = _kinyarwanda_message(acct.customer, pts, acct, tier_upgraded)
    return {
        "account":       acct,
        "points_earned": pts,
        "new_balance":   acct.points_balance,
        "lifetime":      acct.lifetime_points,
        "tier":          acct.tier,
        "tier_label":    TIERS[acct.tier]["label"],
        "tier_upgraded": tier_upgraded,
        "rwf_value":     points_to_rwf(acct.points_balance),
        "message":       msg,
        "whatsapp_url":  _wa_url(acct.customer.phone, msg),
    }


def redeem_points(customer_id: int, points_to_use: int,
                  sale_amount: float) -> dict | None:
    """
    Redeem points for a discount.
    Returns discount info or None if validation fails.
    Caller must db.session.commit() after.
    """
    acct = LoyaltyAccount.query.filter_by(customer_id=customer_id).first()
    if not acct:
        return None
    if points_to_use % 100 != 0:
        return None
    if acct.points_balance < points_to_use:
        return None

    discount = points_to_rwf(points_to_use)
    if discount > sale_amount * MAX_REDEEM_PCT:
        return None

    acct.points_balance -= points_to_use
    db.session.add(LoyaltyTransaction(
        account_id=acct.id, points=-points_to_use, transaction_type="redeem",
        note=f"Gukoresha amanota: -{points_to_use} pts = -{discount:,} RWF",
    ))
    db.session.flush()
    return {"discount_rwf": discount, "points_used": points_to_use,
            "new_balance": acct.points_balance}


def manual_adjust(customer_id: int, points: int, note: str) -> LoyaltyAccount:
    """Award or deduct points manually (staff correction / welcome bonus)."""
    acct = get_or_create_account(customer_id)
    acct.points_balance  += points
    acct.lifetime_points += max(0, points)  # only positive adjustments count toward tier
    acct.tier = calculate_tier(acct.lifetime_points)
    db.session.add(LoyaltyTransaction(
        account_id=acct.id, points=points, transaction_type="manual", note=note,
    ))
    db.session.flush()
    return acct


# ── Kinyarwanda WhatsApp message ──────────────────────────────────────────────

def _kinyarwanda_message(customer, pts_earned: int,
                          acct: LoyaltyAccount, tier_upgraded: bool) -> str:
    first = customer.name.split()[0]
    tier  = TIERS[acct.tier]
    value = points_to_rwf(acct.points_balance)

    lines = [
        f"Muraho {first} 👋",
        "",
        f"Murakoze kugura kuri {PHARMACY_NAME}!",
        "",
        f"✅ Mwinjiye amanota *{pts_earned}* uyu munsi.",
        f"💰 Amanota yanyu: *{acct.points_balance} pts*",
        f"    (agaciro: {value:,} RWF)",
        f"🏆 Ingereko: *{tier['label']}*",
    ]

    if tier_upgraded:
        lines += ["", f"🎉 Amahoro! Mwazamutse: *{tier['label']}*!"]
    elif tier["next"] and tier["next_at"]:
        needed = tier["next_at"] - acct.lifetime_points
        if needed > 0:
            next_label = TIERS[tier["next"]]["label"]
            lines += ["", f"⭐ Mukeneye *{needed} pts* gusa kugira ngo",
                      f"   mujye ku ngereko ya {next_label}!"]

    lines += [
        "",
        "Kugira ngo mukoreshe amanota yanyu,",
        "mubwire nimero ya telefoni igihe mukigurana.",
        "",
        f"📞 {PHARMACY_PHONE}",
        "Murakoze cyane! 🙏",
    ]
    return "\n".join(lines)


def _wa_url(phone: str, message: str) -> str:
    digits = "".join(filter(str.isdigit, phone))
    if digits.startswith("0"):
        digits = "250" + digits[1:]
    return f"https://wa.me/{digits}?text={quote(message)}"


# ── Dashboard summary ─────────────────────────────────────────────────────────

def loyalty_summary() -> dict:
    total_members = LoyaltyAccount.query.count()
    total_pts     = db.session.query(func.sum(LoyaltyAccount.points_balance)).scalar() or 0
    tiers = {t: LoyaltyAccount.query.filter_by(tier=t).count()
             for t in ("bronze", "silver", "gold")}
    recent = (LoyaltyTransaction.query
              .order_by(LoyaltyTransaction.created_at.desc())
              .limit(8).all())
    return {
        "total_members":   total_members,
        "total_points":    total_pts,
        "total_rwf_value": points_to_rwf(total_pts),
        "tiers":           tiers,
        "recent":          recent,
        "TIERS":           TIERS,
        "points_to_rwf":   points_to_rwf,
    }
