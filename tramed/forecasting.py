"""
Demand forecasting for Pharmacie Tramed.

Approach:
  1. Aggregate daily sales per product from the last 90 days.
  2. Fit a linear trend on the most recent 30 days (numpy polyfit).
  3. Compute day-of-week multipliers from the full 90-day window to
     capture weekly seasonality (e.g. pharmacy busier on Mondays).
  4. Project forward: predicted_day = trend(day_index) * dow_multiplier,
     clamped to >= 0.
  5. Derive reorder recommendation from predicted demand vs current stock.
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import func
from database import db, Product, Sale, SaleItem

LEAD_TIME_DAYS = 3    # days between placing order and receiving stock
SAFETY_DAYS = 7       # extra buffer days of stock to always keep


# ── Data layer ────────────────────────────────────────────────────────────────

def _daily_sales_df(product_id: int, days: int = 90) -> pd.DataFrame:
    """Return a DataFrame with one row per day, qty = units sold."""
    end = datetime.utcnow().replace(hour=23, minute=59, second=59)
    start = end - timedelta(days=days - 1)

    rows = (
        db.session.query(
            func.date(Sale.created_at).label("date"),
            func.sum(SaleItem.quantity).label("qty"),
        )
        .join(SaleItem, SaleItem.sale_id == Sale.id)
        .filter(
            SaleItem.product_id == product_id,
            Sale.created_at >= start,
            Sale.created_at <= end,
        )
        .group_by(func.date(Sale.created_at))
        .all()
    )

    date_range = pd.date_range(start=start.date(), end=end.date(), freq="D")
    df = pd.DataFrame({"date": date_range, "qty": 0.0})
    df["date"] = pd.to_datetime(df["date"])

    for row in rows:
        mask = df["date"] == pd.Timestamp(row.date)
        df.loc[mask, "qty"] = float(row.qty)

    df["day_index"] = range(len(df))
    df["dow"] = df["date"].dt.dayofweek   # 0 = Monday
    return df


# ── Model ─────────────────────────────────────────────────────────────────────

def forecast_product(product_id: int, horizon: int = 30) -> dict:
    """
    Forecast daily demand for `horizon` days starting tomorrow.

    Returns a dict with:
      avg_daily        — mean daily demand (last 30 days)
      trend_slope      — units/day change from linear fit
      trend_label      — 'up' | 'flat' | 'down'
      forecast_7d/14d/30d — total predicted units for those windows
      daily_forecasts  — list of horizon floats (tomorrow … tomorrow+horizon)
      historical_dates — last 30 days date labels for chart
      historical_qty   — last 30 days actual quantities for chart
      forecast_dates   — forecast date labels for chart
    """
    df = _daily_sales_df(product_id, days=90)

    # Products with zero sales get a zero forecast
    if df["qty"].sum() == 0:
        today = datetime.utcnow().date()
        future_dates = [
            (today + timedelta(days=i)).strftime("%d %b")
            for i in range(1, horizon + 1)
        ]
        last30 = df.tail(30)
        return {
            "avg_daily": 0.0,
            "trend_slope": 0.0,
            "trend_label": "flat",
            "forecast_7d": 0,
            "forecast_14d": 0,
            "forecast_30d": 0,
            "daily_forecasts": [0.0] * horizon,
            "historical_dates": last30["date"].dt.strftime("%d %b").tolist(),
            "historical_qty": last30["qty"].tolist(),
            "forecast_dates": future_dates,
        }

    # ── 1. Day-of-week multipliers ────────────────────────────────────────────
    overall_mean = df["qty"].mean()
    dow_multipliers = np.ones(7)
    for dow in range(7):
        subset = df[df["dow"] == dow]["qty"]
        if len(subset) > 0 and overall_mean > 0:
            dow_multipliers[dow] = subset.mean() / overall_mean

    # ── 2. Linear trend on last 30 days ──────────────────────────────────────
    recent = df.tail(30).copy()
    x = recent["day_index"].values.astype(float)
    y = recent["qty"].values.astype(float)

    # Deseasonalise before fitting trend so day-of-week noise doesn't bias slope
    dow_vals = recent["dow"].values
    y_deseasonalised = y / dow_multipliers[dow_vals]
    coeffs = np.polyfit(x, y_deseasonalised, 1)   # [slope, intercept]
    slope = coeffs[0]

    avg_daily = float(recent["qty"].mean())

    # ── 3. Project forward ────────────────────────────────────────────────────
    today = datetime.utcnow().date()
    last_index = int(df["day_index"].max())

    daily_forecasts = []
    forecast_dates = []
    for i in range(1, horizon + 1):
        future_date = today + timedelta(days=i)
        future_index = last_index + i
        dow = future_date.weekday()

        # Reseasonalise: trend_value × day-of-week multiplier
        trend_val = coeffs[0] * future_index + coeffs[1]
        predicted = max(0.0, trend_val * dow_multipliers[dow])
        daily_forecasts.append(round(predicted, 2))
        forecast_dates.append(future_date.strftime("%d %b"))

    # Trend label: slope threshold = 0.03 units/day (~1 unit per month)
    if slope > 0.03:
        trend_label = "up"
    elif slope < -0.03:
        trend_label = "down"
    else:
        trend_label = "flat"

    last30 = df.tail(30)
    return {
        "avg_daily": round(avg_daily, 2),
        "trend_slope": round(float(slope), 4),
        "trend_label": trend_label,
        "forecast_7d": round(sum(daily_forecasts[:7])),
        "forecast_14d": round(sum(daily_forecasts[:14])),
        "forecast_30d": round(sum(daily_forecasts[:30])),
        "daily_forecasts": daily_forecasts,
        "historical_dates": last30["date"].dt.strftime("%d %b").tolist(),
        "historical_qty": [float(v) for v in last30["qty"].tolist()],
        "forecast_dates": forecast_dates,
    }


# ── Reorder logic ─────────────────────────────────────────────────────────────

def reorder_recommendation(product: "Product", forecast: dict) -> dict:
    """
    Returns urgency level and recommended order quantity.

    urgency:
      critical — stock will run out before new stock could arrive
      urgent   — stock will run out within the safety buffer window
      soon     — stock will last < 14 days
      ok       — stock is comfortable
    """
    stock = product.stock_quantity
    avg_daily = forecast["avg_daily"]

    days_remaining = (stock / avg_daily) if avg_daily > 0 else 999.0

    if stock <= 0 or days_remaining <= LEAD_TIME_DAYS:
        urgency = "critical"
    elif days_remaining <= LEAD_TIME_DAYS + SAFETY_DAYS:
        urgency = "urgent"
    elif days_remaining <= 14:
        urgency = "soon"
    else:
        urgency = "ok"

    # Order enough to cover 14-day demand + safety buffer, minus what's in stock
    target = forecast["forecast_14d"] + avg_daily * SAFETY_DAYS
    reorder_qty = max(0, round(target - stock))

    return {
        "days_remaining": round(days_remaining, 1),
        "urgency": urgency,
        "reorder_qty": reorder_qty,
    }


# ── Bulk summary (used by the forecast page) ──────────────────────────────────

URGENCY_ORDER = {"critical": 0, "urgent": 1, "soon": 2, "ok": 3}


def all_product_forecasts() -> list[dict]:
    """Return forecast + recommendation for every product, sorted by urgency."""
    products = Product.query.order_by(Product.name).all()
    results = []
    for p in products:
        fc = forecast_product(p.id, horizon=30)
        rec = reorder_recommendation(p, fc)
        results.append({"product": p, "forecast": fc, "recommendation": rec})
    results.sort(key=lambda r: URGENCY_ORDER[r["recommendation"]["urgency"]])
    return results
