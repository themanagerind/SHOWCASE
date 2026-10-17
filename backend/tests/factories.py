import itertools

from geoalchemy2.elements import WKTElement

from app.models import AdminUser, Customer, Retailer, User

_seq = itertools.count(1)


def make_user(db, phone: str | None = None) -> User:
    user = User(phone=phone or f"+9190000{next(_seq):05d}")
    db.add(user)
    db.flush()
    return user


def make_customer(db, **kw) -> Customer:
    c = Customer(user_id=make_user(db).id, **kw)
    db.add(c)
    db.flush()
    return c


def make_admin(db) -> AdminUser:
    a = AdminUser(user_id=make_user(db).id)
    db.add(a)
    db.flush()
    return a


def point(lat: float, lng: float) -> WKTElement:
    return WKTElement(f"POINT({lng} {lat})", srid=4326)


def make_retailer(db, user: User | None = None, **kw) -> Retailer:
    n = next(_seq)
    defaults = dict(
        slug=f"shop-{n}",
        shop_name=f"Shop {n}",
        category="electronics",
        address_line="1 MG Road",
        city="indore",
        pincode="452001",
        location=point(22.7196, 75.8577),
    )
    defaults.update(kw)
    r = Retailer(user_id=(user or make_user(db)).id, **defaults)
    db.add(r)
    db.flush()
    return r


def make_subscription(db, retailer: Retailer, plan_code: str = "BASIC", status: str = "ACTIVE"):
    from sqlalchemy import select

    from app.models import Plan, Subscription
    from app.models.enums import SubscriptionStatus

    plan = db.scalar(select(Plan).where(Plan.code == plan_code))
    sub = Subscription(retailer_id=retailer.id, plan_id=plan.id, status=SubscriptionStatus(status))
    db.add(sub)
    db.flush()
    return sub


def make_shop(db, plan_code: str | None = "BASIC", status: str = "ACTIVE", **kw) -> Retailer:
    retailer = make_retailer(db, **kw)
    if plan_code:
        make_subscription(db, retailer, plan_code, status)
    return retailer


def product_data(n: int = 1, **kw) -> dict:
    data = {"name": f"Product {n}", "price_paise": 10000 * n, "stock_qty": 5}
    data.update(kw)
    return data
