from django.db.models import TextChoices


class UserRoleChoices(TextChoices):
    """A class that contains the available user roles."""

    ADMIN = "ADMIN", "Admin"
    TAQABETH_ENFORCER = "TAQABETH_ENFORCER", "Taqabeth Enforcer"
    JEWELLERY_INSPECTOR = "JEWELLERY_INSPECTOR", "Jewellery Inspector"
    JEWELLERY_BUYER = "JEWELLERY_BUYER", "Jewellery Buyer"


class UserRoleBusinessChoices(TextChoices):
    """A class that contains the available user roles."""

    SELLER = "SELLER", "Seller"
    JEWELER = "JEWELER", "Jeweler"
    INVESTOR = "INVESTOR", "Investor"
    MANUFACTURER = "MANUFACTURER", "Manufacturer"


class UserStatus(TextChoices):
    """Enum for specifying the status of a user account."""

    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    PENDING = "PENDING", "Pending"
    SUSPEND = "SUSPEND", "Suspend"
    DELETED = "DELETED", "Deleted"


class UserType(TextChoices):
    """Enum for specifying whether the user is an individual or a business."""

    INDIVIDUAL = "INDIVIDUAL", "Individual"
    BUSINESS = "BUSINESS", "Business"


class SubscriptionBillingFrequencyChoices(TextChoices):
    MONTHLY = "MONTHLY", "Monthly"
    YEARLY = "YEARLY", "Yearly"


class SubscriptionStatusChoices(TextChoices):
    # Subscription is active and in good standing
    ACTIVE = "ACTIVE", "Active"

    # User is in a free or discounted trial period
    TRIALING = "TRIALING", "Trialing"

    # Suspended due to an issue (e.g., failed payment, policy violation)
    SUSPENDED = "SUSPENDED", "Suspended"

    # Manually cancelled by user before renewal
    CANCELLED = "CANCELLED", "Cancelled"

    # Subscription naturally ended without renewal
    EXPIRED = "EXPIRED", "Expired"

    # Forcefully terminated by provider (e.g., fraud, TOS violation)
    TERMINATED = "TERMINATED", "Terminated"

    # Failed to activate due to error (e.g., payment failure, internal error)
    FAILED = "FAILED", "Failed"

    # Subscription creation started but not finished (e.g., checkout abandoned)
    PENDING = "PENDING", "Pending"


class Gender(TextChoices):
    """Enum for specifying the gender of a user."""

    MALE = "MALE", "Male"
    FEMALE = "FEMALE", "Female"
    OTHER = "OTHER", "Other"


class MusharakahClientType(TextChoices):
    """Enum for categorizing Musharakah clients based on their growth stage."""

    NEW = "NEW", "New"
    GROWTH = "GROWTH", "Growth"
    REPUTABLE = "REPUTABLE", "Reputable"


class BusinessType(TextChoices):
    """Enum for specifying different types of business type."""

    ESTABLISHMENT = "ESTABLISHMENT", "Establishment"
    WLL = "WLL", "WLL (With Limited Liability)"


class DocumentType(TextChoices):
    """Enum for specifying different types of business-related documents."""

    CR_CERTIFICATE = "CR_CERTIFICATE", "CR Certificate"
    VAT_CERTIFICATE = "VAT_CERTIFICATE", "VAT Certificate"
    AUTHORIZATION_LETTER = "AUTHORIZATION_LETTER", "Authorization Letter"


class SuspendingRoleChoice(TextChoices):
    """Enum for specifying the type of user who suspended the account."""

    ADMIN = "ADMIN", "Admin"
    BUSINESS_OWNER = "BUSINESS_OWNER", "Business Owner"


class Language(TextChoices):
    ARABIC = "ar", "Arabic"
    ENGLISH = "en", "English"


class ShareholderRole(TextChoices):
    DIRECTOR = "DIRECTOR", "Director"
    AUTHORIZED_SIGNATORY = "AUTHORIZED_SIGNATORY", "Authorized Signatory"
    SHAREHOLDER = "SHAREHOLDER", "Shareholder"


class DeviceType(TextChoices):
    ANDROID = "ANDROID", "Android"
    IOS = "IOS", "iOS"
    WEB = "WEB", "Web"


class PlatformFeeType(TextChoices):
    PERCENTAGE = "PERCENTAGE", "Percentage"
    AMOUNT = "AMOUNT", "Amount"


class TransactionType(TextChoices):
    """Represents the type of wallet transaction type."""

    DEPOSIT = "DEPOSIT", "Deposit"
    WITHDRAWAL = "WITHDRAWAL", "Withdrawal"
    PAYMENT = "PAYMENT", "Payment"
    PROFIT_DISTRIBUTION = "PROFIT_DISTRIBUTION", "Profit Distribution"


class TransactionStatus(TextChoices):
    """Represents the status of the transaction."""

    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    SUCCESS = "SUCCESS", "Success"
    FAILED = "FAILED", "Failed"


class TransferVia(TextChoices):
    BENEFIT_PAY = "BENEFIT_PAY", "Benefit Pay"
    CREDIMAX = "CREDIMAX", "Credimax"
    ORGANIZATION_ADMIN = "ORGANIZATION_ADMIN", "Organization Admin"


class WebhookEventType(TextChoices):
    PAYMENT = "PAYMENT", "Payment"
    REFUND = "REFUND", "Refund"
    OTHERS = "OTHERS", "Others"
    AUTHENTICATION = "AUTHENTICATION", "Authentication"


class WebhookCallStatus(TextChoices):
    SUCCESS = "SUCCESS", "Success"
    FAILURE = "FAILURE", "Failure"
    PENDING = "PENDING", "Pending"
    RECEIVED = "RECEIVED", "Received"


class RiskLevel(TextChoices):
    LOW = "LOW", "Low"
    MEDIUM = "MEDIUM", "Medium"
    HIGH = "HIGH", "High"


class PlatformChoices(TextChoices):
    ANDROID = "ANDROID", "Android"
    IOS = "IOS", "iOS"


class MusharakahContractTerminationPaymentType(TextChoices):
    INVESTOR_LOGISTIC_FEE_PAYMENT_TRANSACTION = (
        "INVESTOR_LOGISTIC_FEE_PAYMENT_TRANSACTION",
        "Investor Logistic Fee Payment Transaction",
    )
    INVESTOR_REFINING_COST_PAYMENT_TRANSACTION = (
        "INVESTOR_REFINING_COST_PAYMENT_TRANSACTION",
        "Investor Refining Cost Payment Transaction",
    )
    INVESTOR_EARLY_TERMINATION_PAYMENT_TRANSACTION = (
        "INVESTOR_EARLY_TERMINATION_PAYMENT_TRANSACTION",
        "Investor Early Termination Payment Transaction",
    )
    JEWELER_SETTLEMENT_PAYMENT_TRANSACTION = (
        "JEWELER_SETTLEMENT_PAYMENT_TRANSACTION",
        "Jeweler Settlement Payment Transaction",
    )


class SubscriptionFeatureChoices(TextChoices):
    """Enum for subscription plan features that can be enabled/disabled."""

    PURCHASE_ASSETS = "PURCHASE_ASSETS", "Purchase/Sell Assets"
    JOIN_POOLS = "JOIN_POOLS", "Join Pools"
    JOIN_MUSHARAKAH = "JOIN_MUSHARAKAH", "Join Musharakah"
