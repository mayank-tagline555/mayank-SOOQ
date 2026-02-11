import uuid
from datetime import datetime

from django.db import models

# Define model short prefixes
MODEL_ALIASES = {
    # Account models
    "User": "usr",
    "Wallet": "wal",
    "Address": "adr",
    "AdminUserRole": "aur",
    "BankAccount": "bac",
    "RoleHistory": "roh",
    "FCMToken": "fcm",
    "Shareholder": "shr",
    "WebhookCall": "wbc",
    "Transaction": "txn",
    "OrganizationRiskLevel": "orl",
    "TransactionAttachment": "txa",
    "Notification": "ntf",
    "Organization": "org",
    "ReceiptSequence": "rsq",
    "BusinessAccount": "bus",
    "UserPreference": "upr",
    "CountryToContinent": "ctc",
    "UserAssignedBusiness": "uab",
    "OrganizationCurrency": "orc",
    "ContactSupportRequest": "csr",
    "BusinessAccountDocument": "doc",
    # Investor models
    "PurchaseRequest": "pur",
    "PreciousItemUnit": "piu",
    "AssetContribution": "acn",
    ### Jeweller models ###
    "JewelryDesign": "jld",
    "JewelryProduct": "jpr",
    "JewelryProductMaterial": "jpm",
    "JewelryProductAttachment": "jpa",
    "MusharakahContractRequest": "mcr",
    "MusharakahContractDesign": "mcd",
    "MusharakahContractRequestAttachment": "mca",
    "MusharakahContractRenewal": "mrn",
    "MusharakahContractTerminationRequest": "mtr",
    "ManufacturingRequest": "mfr",
    "ManufacturingTarget": "mft",
    "JewelryProduction": "jlp",
    "ProductionPayment": "prp",
    "JewelryProductStonePrice": "psp",
    "JewelryProductInspectionAttachment": "pia",
    "MusharakahContractRequestQuantity": "mrq",
    "ManufacturingProductRequestedQuantity": "mpq",
    "JewelryStock": "jst",
    "JewelryProductMarketplace": "jmk",
    "JewelryProductMarketplaceImage": "jmi",
    "JewelryStockRestockRequest": "jsr",
    "JewelryStockSale": "jss",
    "JewelryProfitDistribution": "jpd",
    "InspectedRejectedJewelryProduct": "irj",
    "InspectionRejectionAttachment": "ira",
    # Manufacturer models
    "ManufacturingEstimationRequest": "mer",
    "ProductManufacturingEstimatedPrice": "mep",
    "CorrectionValue": "crv",
    # Seller models
    "PreciousItem": "pit",
    "PreciousItemImage": "pim",
    "PreciousMetal": "pmt",
    "PreciousStone": "pst",
    # Subscription models
    "SubscriptionPlan": "sub",
    "BusinessSubscriptionPlan": "bsp",
    # Admin models
    "Pool": "pol",
    "GlobalMetal": "gme",
    "MaterialItem": "mit",
    "PoolContribution": "plc",
    "MusharakahContract": "muc",
    "MusharakahContractMaterial": "mcm",
    "MetalPriceHistory": "mph",
    "StoneCutShape": "sct",
    "MetalCaratType": "mct",
    "JewelryProductType": "jpt",
    "JewelryProductColor": "jpc",
    "MarketplaceProduct": "mpp",
    "BillingDetails": "bld",
    "OrganizationBankAccount": "oba",
    "BusinessSavedCardToken": "bst",
    "SubscriptionBillingHistory": "sbh",
    "MusharakahDurationChoices": "mdc",
    "StoneClarity": "scl",
}


def generate_custom_id(prefix: str) -> str:
    """Generates a unique custom ID with a prefix."""
    timestamp = datetime.now().strftime("%d%m%y")  # Format: DDMMYY
    short_uuid = uuid.uuid4().hex[:6]  # 6-character UUID
    return f"{prefix}_{timestamp}{short_uuid}"


class CustomIDMixin(models.Model):
    """Mixin to generate a custom unique ID for models."""

    id = models.CharField(
        primary_key=True,
        max_length=25,
        editable=False,
        unique=True,
    )

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        """Automatically assigns a custom ID when an instance is created."""
        super().__init__(*args, **kwargs)
        if not self.id:
            prefix = MODEL_ALIASES.get(
                self.__class__.__name__, self.__class__.__name__[:3].lower()
            )
            self.id = generate_custom_id(prefix)
