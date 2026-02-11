from django.db.models import TextChoices


class RequestStatus(TextChoices):
    PENDING = "PENDING", "Pending"
    ADMIN_APPROVED = "ADMIN_APPROVED", "Admin Approved"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"


class AssetContributionStatus(TextChoices):
    PENDING = "PENDING", "Pending"
    ADMIN_APPROVED = "ADMIN_APPROVED", "Admin Approved"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    TERMINATED = "TERMINATED", "Terminated"


class MusharakahContractStatus(TextChoices):
    NOT_ASSIGNED = "NOT_ASSIGNED", "Not Assigned"
    ACTIVE = "ACTIVE", "Active"
    COMPLETED = "COMPLETED", "Completed"
    TERMINATED = "TERMINATED", "Terminated"
    RENEW = "RENEW", "Renew"
    CLOSED = "CLOSED", "Closed"
    UNDER_TERMINATION = "UNDER_TERMINATION", "Under Termination"


class DesignType(TextChoices):
    SINGLE = "SINGLE", "Single"
    COLLECTION = "COLLECTION", "Collection"
    BOTH = "BOTH", "Both"


class ManufactureType(TextChoices):
    TENDER = "TENDER", "Tender"
    DIRECT_MANUFACTURER = "DIRECT_MANUFACTURER", "Direct Manufacturer"


class MaterialSource(TextChoices):
    CASH = "CASH", "Cash"
    MUSHARAKAH = "MUSHARAKAH", "Musharakah"
    ASSET = "ASSET", "Asset"
    MUSHARAKAH_AND_ASSET = "MUSHARAKAH_AND_ASSET", "Musharakah and Asset"


class ProductionStatus(TextChoices):
    NOT_STARTED = "NOT_STARTED", "Not Started"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    ON_HOLD = "ON_HOLD", "On Hold"
    COMPLETED = "COMPLETED", "Completed"


class InspectionStatus(TextChoices):
    PENDING = "PENDING", "Pending"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    COMPLETED = "COMPLETED", "Completed"
    ADMIN_APPROVAL = "ADMIN_APPROVAL", "Admin Approval"


class DeliveryStatus(TextChoices):
    PENDING = "PENDING", "Pending"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY", "Out for delivery"
    DELIVERED = "DELIVERED", "Delivered"


class Ownership(TextChoices):
    JEWELER = "JEWELER", "Jeweler"
    INVESTOR = "INVESTOR", "Investor"


class ContractTerminator(TextChoices):
    JEWELER = "JEWELER", "Jeweler"
    ADMIN = "ADMIN", "Admin"
    INVESTOR = "INVESTOR", "Investor"


class ManufacturingStatus(TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    QUOTATION_SUBMITTED = "QUOTATION_SUBMITTED", "Quotation Submitted"
    PAYMENT_PENDING = "PAYMENT_PENDING", "Payment Pending"
    COMPLETED = "COMPLETED", "Completed"


class ProductProductionStatus(TextChoices):
    PENDING = "PENDING", "Pending"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    ON_HOLD = "ON_HOLD", "On Hold"
    COMPLETED = "COMPLETED", "Completed"


class InspectionRejectedByChoices(TextChoices):
    JEWELER = "JEWELER", "Jeweler"
    JEWELLERY_INSPECTOR = "JEWELLERY_INSPECTOR", "Jewellery Inspector"


class JewelryProductAttachmentUploadedByChoices(TextChoices):
    ADMIN = "ADMIN", "Admin"
    JEWELLERY_INSPECTOR = "JEWELLERY_INSPECTOR", "Jewellery Inspector"
    MANUFACTURER = "MANUFACTURER", "Manufacturer"


class CostRetailPaymentOption(TextChoices):
    PAY_COST = "PAY_COST", "Pay Cost"
    PAY_RETAIL = "PAY_RETAIL", "Pay Retail"


class RefineSellPaymentOption(TextChoices):
    REFINE = "REFINE", "Refine"
    SELL = "SELL", "Sell"


class LogisticCostPayableBy(TextChoices):
    JEWELER = "JEWELER", "Jeweler"
    INVESTOR = "INVESTOR", "Investor"


class ImpactedParties(TextChoices):
    INVESTOR = "INVESTOR", "Investor"
    JEWELER = "JEWELER", "Jeweler"


class StockLocation(TextChoices):
    SHOWROOM = "SHOWROOM", "Showroom"
    MARKETPLACE = "MARKETPLACE", "Marketplace"
    BOTH = "BOTH", "Both"


class DeliveryRequestStatus(TextChoices):
    NEW = "NEW", "New"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    DELIVERED = "DELIVERED", "Delivered"


class StockStatus(TextChoices):
    IN_STOCK = "IN_STOCK", "In Stock"
    OUT_OF_STOCK = "OUT_OF_STOCK", "Out of Stock"
