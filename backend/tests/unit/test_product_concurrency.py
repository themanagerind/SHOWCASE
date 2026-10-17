"""Two parallel adds for the last free slot: exactly one must win (row lock in product_service)."""
import threading

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import Forbidden
from app.models import Customer, Product, Retailer, Subscription, User
from app.services import product_service as ps
from tests.factories import make_shop, product_data


def test_parallel_adds_cannot_exceed_limit(engine):
    with Session(engine) as s:
        shop = make_shop(s, "BASIC")
        user = s.get(User, shop.user_id)
        for i in range(4):
            ps.add_product(s, shop, user, product_data(i))
        s.commit()
        shop_id, user_id = shop.id, user.id

    results: list[str] = []
    barrier = threading.Barrier(2)

    def worker(n):
        with Session(engine) as s:
            shop = s.get(Retailer, shop_id)
            user = s.get(User, user_id)
            barrier.wait()
            try:
                ps.add_product(s, shop, user, product_data(10 + n))
                results.append("ok")
            except Forbidden:
                results.append("limit")

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    try:
        assert sorted(results) == ["limit", "ok"]
        with Session(engine) as s:
            assert ps.active_count(s, shop_id) == 5
    finally:
        with Session(engine) as s:
            s.execute(delete(Product).where(Product.retailer_id == shop_id))
            s.execute(delete(Subscription).where(Subscription.retailer_id == shop_id))
            s.execute(delete(Retailer).where(Retailer.id == shop_id))
            s.execute(delete(Customer).where(Customer.user_id == user_id))
            s.execute(delete(User).where(User.id == user_id))
            s.commit()
            assert s.scalar(select(Retailer).where(Retailer.id == shop_id)) is None
