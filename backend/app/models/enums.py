import enum


class AdminRole(enum.StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"
    SUPPORT = "SUPPORT"


class JoinSource(enum.StrEnum):
    LINK = "LINK"
    QR = "QR"
    DISCOVERY = "DISCOVERY"



class BillingPeriod(enum.StrEnum):
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"


class SubscriptionStatus(enum.StrEnum):
    TRIAL = "TRIAL"
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


LIVE_SUBSCRIPTION_STATUSES = (SubscriptionStatus.TRIAL, SubscriptionStatus.ACTIVE, SubscriptionStatus.GRACE)


class OfferType(enum.StrEnum):
    PERCENT = "PERCENT"
    FIXED_DISCOUNT = "FIXED_DISCOUNT"
    CUSTOM_PRICE = "CUSTOM_PRICE"


class SubscriptionPaymentStatus(enum.StrEnum):
    CREATED = "CREATED"
    PAID = "PAID"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"






class OrderStatus(enum.StrEnum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAID = "PAID"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"


class ShipmentStatus(enum.StrEnum):
    CREATED = "CREATED"
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    RTO = "RTO"
    CANCELLED = "CANCELLED"


class ReviewSource(enum.StrEnum):
    BOOKING = "BOOKING"
    ORDER = "ORDER"
    CREDIT_USE = "CREDIT_USE"


class ShopEventType(enum.StrEnum):
    SHOP_VIEW = "shop_view"
    PRODUCT_VIEW = "product_view"
    FAVOURITE_ADD = "favourite_add"
    WHATSAPP_CLICK = "whatsapp_click"
    CALL_CLICK = "call_click"
    BOOKING_START = "booking_start"
    BOOKING_CONFIRMED = "booking_confirmed"


class LeadStatus(enum.StrEnum):
    NEW = "NEW"
    CONTACTED = "CONTACTED"
    CONVERTED = "CONVERTED"
    DISMISSED = "DISMISSED"


class NotificationChannel(enum.StrEnum):
    PUSH = "PUSH"
    WHATSAPP = "WHATSAPP"
    SMS = "SMS"
    IN_APP = "IN_APP"


class NotificationStatus(enum.StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
