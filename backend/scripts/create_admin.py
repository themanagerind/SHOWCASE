"""Create (or promote) a platform admin.

Usage: .venv/bin/python -m scripts.create_admin --phone 9876543210 [--role SUPER_ADMIN|SUPPORT]
The person then logs in with OTP as usual and sees the admin screens.
"""
import argparse

from sqlalchemy import select

from app.core.phone import normalize_indian_mobile
from app.db.session import SessionLocal
from app.models import AdminUser, Customer, User
from app.models.enums import AdminRole


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phone", required=True)
    ap.add_argument("--role", default="SUPER_ADMIN", choices=[r.value for r in AdminRole])
    args = ap.parse_args()
    phone = normalize_indian_mobile(args.phone)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.phone == phone))
        if user is None:
            user = User(phone=phone)
            db.add(user)
            db.flush()
            db.add(Customer(user_id=user.id))
        admin = db.scalar(select(AdminUser).where(AdminUser.user_id == user.id))
        if admin is None:
            db.add(AdminUser(user_id=user.id, role=AdminRole(args.role)))
        else:
            admin.role, admin.is_active = AdminRole(args.role), True
        db.commit()
    print(f"{phone} is now {args.role}")


if __name__ == "__main__":
    main()
