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
