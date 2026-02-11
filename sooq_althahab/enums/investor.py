from django.db.models import TextChoices


class PurchaseRequestStatus(TextChoices):
    """Represents the different statuses of a purchase requests status."""

    PENDING = "PENDING", "Pending"
    REJECTED = "REJECTED", "Rejected"
    CONFIRMED = "CONFIRMED", "Confirmed"
    COMPLETED = "COMPLETED", "Completed"
    APPROVED = "APPROVED", "Approved"
    PENDING_SELLER_PRICE = "PENDING_SELLER_PRICE", "Pending Seller Price"
    PENDING_INVESTOR_CONFIRMATION = (
        "PENDING_INVESTOR_CONFIRMATION",
        "Pending Investor Confirmation",
    )


class RequestType(TextChoices):
    """Represents the type of request"""

    PURCHASE = "PURCHASE", "Purchase Request"
    SALE = "SALE", "Sale Request"
    JEWELRY_DESIGN = "JEWELRY_DESIGN", "Jewelry Design"


class ContributionType(TextChoices):
    """Represents the type of contribution."""

    POOL = "POOL", "Pool"
    MUSHARAKAH = "MUSHARAKAH", "Musharakah"
    PRODUCTION_PAYMENT = "PRODUCTION_PAYMENT", "Production Payment"
