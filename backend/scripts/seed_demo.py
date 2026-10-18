"""Dev-only demo data: one shop with an ACTIVE BASIC subscription and a few products.

Usage: .venv/bin/python -m scripts.seed_demo
"""
from datetime import timedelta

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Customer, Plan, Product, Retailer, Subscription, User
from app.core import clock
from app.core.dates import add_months
from app.models import SubscriptionPayment
from app.models.enums import BillingPeriod, SubscriptionPaymentStatus, SubscriptionStatus
from app.services.retailer_service import to_point

PRODUCTS = [
    ("Samsung 43\" Smart TV", 3299000, 3899000, 150000),
    ("Bajaj Mixer Grinder 750W", 349900, 499900, 20000),
    ("Philips LED Bulb (pack of 4)", 39900, 59900, 4000),
    ("Havells Ceiling Fan", 289900, 349900, 15000),
]


def main() -> None:
    if get_settings().env == "prod":
        raise SystemExit("refusing to seed demo data in prod")
    with SessionLocal() as db:
        if db.scalar(select(Retailer).where(Retailer.slug == "sharma-electronics")):
            print("demo shop already exists")
            return
        user = User(phone="+919876543210", name="Ramesh Sharma")
        db.add(user)
        db.flush()
        db.add(Customer(user_id=user.id))
        shop = Retailer(
            user_id=user.id, slug="sharma-electronics", shop_name="शर्मा इलेक्ट्रॉनिक्स", category="Electronics",
            description="टीवी, पंखे, मिक्सर और हर तरह का इलेक्ट्रॉनिक सामान — भरोसे के साथ 25 साल से।",
            address_line="12, एम.जी. रोड, राजवाड़ा के पास", city="indore", state="Madhya Pradesh", pincode="452001",
            location=to_point(22.7196, 75.8577), timings={"mon": [["10:00", "20:00"]], "sun": [["11:00", "14:00"]]},
            phone="+919876543210", whatsapp_number="+919876543210",
        )
        db.add(shop)
        db.flush()
        _paid_subscription(db, shop, "BASIC")
        for name, price, mrp, discount in PRODUCTS:
            db.add(Product(retailer_id=shop.id, name=name, price_paise=price, mrp_paise=mrp,
                           wallet_discount_paise=discount, stock_qty=5, activated_at=func.now()))
        _extra_shops(db)
        db.commit()
        print("seeded /sharma-electronics + nearby demo shops")


# (slug, name, category, plan, pincode, lat, lng, rating) around Rajwada, Indore
EXTRA_SHOPS = [
    ("gupta-kirana", "गुप्ता किराना स्टोर", "Grocery", "PRO", "452002", 22.7270, 75.8640, 4.6),
    ("verma-fashion", "वर्मा फ़ैशन हब", "Clothing", "PREMIUM", "452010", 22.7450, 75.8800, 4.2),
    ("jain-mobile", "जैन मोबाइल पॉइंट", "Electronics", "BASIC", "452001", 22.7180, 75.8600, 4.9),
    ("mehta-sweets", "मेहता स्वीट्स", "Sweets", "BASIC", "452018", 22.7000, 75.8700, 4.8),  # other pincode: hidden
    ("delhi-appliances", "दिल्ली अप्लायंसेज़", "Electronics", "PREMIUM", "110006", 28.6562, 77.2410, 4.7),  # ~700 km
]

# slug -> [(name, price, mrp, discount)] ; BASIC shops' products never appear in product search
EXTRA_PRODUCTS = {
    "gupta-kirana": [("Prestige Mixer Grinder 500W", 289900, 349900, 15000), ("Tata Salt 1kg", 2800, 3000, 200)],
    "verma-fashion": [("Cotton Kurta (Men)", 89900, 129900, 5000)],
    "jain-mobile": [("Mixer Jar Set", 59900, 79900, 3000)],
    "delhi-appliances": [("Philips Mixer Grinder 750W", 459900, 599900, 25000), ("Usha Table Fan", 249900, 299900, 10000)],
}


def _paid_subscription(db, shop: Retailer, plan_code: str) -> None:
    """Demo shops get a paid monthly period that started 10 days ago (status is derived from paid periods)."""
    plan = db.scalar(select(Plan).where(Plan.code == plan_code))
    start = clock.now() - timedelta(days=10)
    sub = Subscription(retailer_id=shop.id, plan_id=plan.id, billing_cycle=BillingPeriod.MONTHLY, status=SubscriptionStatus.ACTIVE,
                       current_period_start=start, current_period_end=add_months(start, 1))
    db.add(sub)
    db.flush()
    db.add(SubscriptionPayment(
        subscription_id=sub.id, plan_id=plan.id, billing_cycle=BillingPeriod.MONTHLY, amount_paise=plan.base_price_paise,
        price_source="BASE", period_start=start, period_end=add_months(start, 1), status=SubscriptionPaymentStatus.PAID,
        gateway="manual", reference="demo-seed", paid_at=start,
    ))


def _extra_shops(db) -> None:
    for i, (slug, name, category, plan_code, pin, lat, lng, rating) in enumerate(EXTRA_SHOPS):
        user = User(phone=f"+91900000010{i}", name=name)
        db.add(user)
        db.flush()
        shop = Retailer(
            user_id=user.id, slug=slug, shop_name=name, category=category,
            address_line="Chandni Chowk" if pin.startswith("110") else "Indore",
            city="delhi" if pin.startswith("110") else "indore",
            pincode=pin, location=to_point(lat, lng), rating_avg=rating, rating_count=20 + i,
            whatsapp_number=f"+91900000010{i}",
        )
        db.add(shop)
        db.flush()
        _paid_subscription(db, shop, plan_code)
        for pname, price, mrp, discount in EXTRA_PRODUCTS.get(slug, []):
            db.add(Product(retailer_id=shop.id, name=pname, price_paise=price, mrp_paise=mrp,
                           wallet_discount_paise=discount, stock_qty=4, activated_at=func.now()))


if __name__ == "__main__":
    main()
