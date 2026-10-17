"""Dev-only demo data: one shop with an ACTIVE BASIC subscription and a few products.

Usage: .venv/bin/python -m scripts.seed_demo
"""
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Customer, Plan, Product, Retailer, Subscription, User
from app.models.enums import SubscriptionStatus
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
        plan = db.scalar(select(Plan).where(Plan.code == "BASIC"))
        db.add(Subscription(retailer_id=shop.id, plan_id=plan.id, status=SubscriptionStatus.ACTIVE))
        for name, price, mrp, discount in PRODUCTS:
            db.add(Product(retailer_id=shop.id, name=name, price_paise=price, mrp_paise=mrp,
                           wallet_discount_paise=discount, stock_qty=5))
        db.commit()
        print("seeded /sharma-electronics")


if __name__ == "__main__":
    main()
