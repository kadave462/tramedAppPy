import os
from anthropic import Anthropic
from database import db, Product

PHARMACY_WHATSAPP = "250788000000"  # TODO: replace with actual pharmacy WhatsApp number
PHARMACY_NAME = "Pharmacie Tramed"
PHARMACY_ADDRESS = "KN 151 St, Kigali, Rwanda"

_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not configured")
        _client = Anthropic(api_key=api_key)
    return _client


def _build_inventory_context():
    products = Product.query.order_by(Product.category, Product.name).all()
    lines = []
    for p in products:
        if p.stock_quantity > p.min_stock_level:
            status = "in stock"
        elif p.stock_quantity > 0:
            status = "low stock"
        else:
            status = "out of stock"
        lines.append(
            f"- {p.name} ({p.category}): {int(p.unit_price):,} RWF — {status} ({p.stock_quantity} units)"
        )
    return "\n".join(lines)


def build_system_prompt():
    inventory = _build_inventory_context()
    return f"""You are a friendly pharmacy assistant for {PHARMACY_NAME}, located at {PHARMACY_ADDRESS}.
You help customers find medications, check availability, understand pricing, and place orders via WhatsApp.

Current inventory:
{inventory}

Guidelines:
- Be concise, helpful, and professional
- Prescription medications require a valid prescription from a doctor
- If a product is out of stock, suggest available alternatives in the same category
- For ordering, direct customers to WhatsApp: wa.me/{PHARMACY_WHATSAPP}
- You can respond in English, French, or Kinyarwanda — match the customer's language
- Never diagnose medical conditions; advise in-person consultation for health concerns
- Keep responses under 3 short paragraphs"""


def chat(messages: list[dict]) -> str:
    """
    messages: list of {{"role": "user"|"assistant", "content": "..."}}
    Returns the assistant reply text.
    """
    client = _get_client()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=build_system_prompt(),
        messages=messages,
    )
    return response.content[0].text
