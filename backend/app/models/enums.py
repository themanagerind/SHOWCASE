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
    CREDIT_USE = "CREDIT_USE"  # legacy (advance/credit flow was dropped in 0002)
    SHOP_DISCOUNT = "SHOP_DISCOUNT"  # confirmed discount on an unlisted item (SPEC 4.4a / 4.7)


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


class WalletOwnerType(enum.StrEnum):
    CUSTOMER = "CUSTOMER"
    RETAILER = "RETAILER"


class WalletEntryType(enum.StrEnum):
    CODE_REDEEMED = "CODE_REDEEMED"            # + customer: THE-MANAGER code value
    BOOKING_HOLD = "BOOKING_HOLD"              # - customer: points for a reservation
    BOOKING_PURCHASED = "BOOKING_PURCHASED"    # + retailer: discount points of a completed purchase
    BOOKING_FORFEITED = "BOOKING_FORFEITED"    # 0 customer: record only, points vanish
    BOOKING_CANCEL_REFUND = "BOOKING_CANCEL_REFUND"  # + customer: retailer cancelled
    REWARD_RESET = "REWARD_RESET"              # - retailer: reset to 0 after a reward payout
    SHOP_DISCOUNT = "SHOP_DISCOUNT"            # - customer: confirmed discount on an unlisted item (SPEC 4.4a)
    SHOP_DISCOUNT_RECEIVED = "SHOP_DISCOUNT_RECEIVED"  # + retailer: same


class RedemptionStatus(enum.StrEnum):
    PENDING = "PENDING"      # saved before calling THE-MANAGER; retried with the same request_id
    CREDITED = "CREDITED"
    REJECTED = "REJECTED"    # 404 / 409 from THE-MANAGER
    ERROR = "ERROR"          # 401 / 503: integration problem, code not consumed


class BookingStatus(enum.StrEnum):
    RESERVED = "RESERVED"
    PURCHASED = "PURCHASED"
    FORFEITED = "FORFEITED"
    CANCELLED_BY_RETAILER = "CANCELLED_BY_RETAILER"


class DiscountRequestStatus(enum.StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class SignupSource(enum.StrEnum):
    DIRECT = "DIRECT"
    THE_MANAGER = "THE_MANAGER"  # arrived through the resident prefill link (SPEC 4.12)
