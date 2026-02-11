"""This module defines various constants used throughout the application."""

ROLE_AND_PERMISSIONS = {
    "Admin": {
        "User": ["view", "change", "delete"],
        "SubAdmin": ["add", "view", "change", "delete"],
        "BusinessRiskLevel": ["change"],
        "BusinessList": ["view"],
        "AdminPurchaseRequest": ["view", "change"],
        "AdminCreatePurchaseRequest": ["add"],
        "Wallet": ["view"],
        "Transaction": ["view"],
        "MusharakahContractRequest": ["add", "view", "change", "delete"],
        "JewelryDesign": ["add", "view", "change", "delete"],
        "ManufacturingRequest": ["add", "view", "change", "delete"],
        "MaterialItem": ["add", "view", "change", "delete"],
        "PreciousItems": ["view"],
        "AdminPreciousItems": ["view"],
        "Pool": ["add", "view", "change", "delete"],
        "PoolContribution": ["add", "view", "change", "delete"],
        "MusharakahContract": ["add", "view", "change", "delete"],
        "MusharakahContractMaterial": ["add", "view", "change", "delete"],
        "MusharakahContractTerminationRequest": ["add", "view", "change", "delete"],
        "Subscription": ["add", "view", "change", "delete"],
        "BankAccount": ["view"],
        "Currency": ["add", "view", "change"],
        "OrganizationCurrency": ["add", "view", "change"],
        "RiskLevel": ["add", "view", "change"],
        "Organization": ["view", "change"],
        "ManageUserSuspension": ["change"],
        "OrganizationBankAccount": ["add", "view", "change"],
        "ManageBusinessAccountSuspension": ["change"],
        "Notification": ["view"],
        "StoneCutShape": ["add", "view", "change"],
        "MetalCaratType": ["add", "view", "change"],
        "StoneClarity": ["add", "view", "change"],
        "Pool": ["add", "view", "change"],
        "PreciousItemsAttributes": ["view"],
        "MusharakahContractRequest": ["view", "change"],
        "JewelryProductType": ["add", "view", "change"],
        "JewelryProductColor": ["add", "view", "change"],
        "MusharakahDuration": ["add", "view", "change"],
        "MusharakahContractTerminate": ["change"],
        "MusharakahContractRenewal": ["add"],
        "JewelryProduction": ["view", "change"],
        "JewelryProductionProduct": ["change"],
        "TaqabethRequest": ["view"],
        "OccupiedStock": ["view"],
        "PreciousItemUnit": ["view"],
        "StockManagement": ["view", "change"],
    },
    "Jeweler": {
        "User": ["change"],
        "Business": ["add", "view", "change", "delete"],
        "Wallet": ["view"],
        "Transaction": ["add", "view"],
        "MusharakahContractRequest": ["add", "view", "change", "delete"],
        "JewelryDesign": ["add", "view", "change", "delete"],
        "ManufacturerBusiness": ["view"],
        "ManufacturingRequest": ["add", "view", "change", "delete"],
        "MaterialItem": ["view"],
        "PreciousItems": ["view"],
        "Pool": ["view"],
        "PoolContribution": ["add", "view", "change", "delete"],
        "MusharakahContract": ["view"],
        "MusharakahContractMaterial": ["view"],
        "MusharakahContractTerminationRequest": ["add", "view", "change", "delete"],
        "Subscription": ["view"],
        "BankAccount": ["change"],
        "ShareHolder": ["add", "view", "change", "delete"],
        "Currency": ["view"],
        "SubUser": ["add", "view"],
        "ManageUserSuspension": ["change"],
        "OrganizationCurrency": ["view"],
        "OrganizationBankAccount": ["view"],
        "Notification": ["view"],
        "BusinessSavedCards": ["add", "view", "change"],
        "PreciousItemsAttributes": ["view"],
        "JewelryDesign": ["add", "view", "change", "delete"],
        "PurchaseRequest": ["add", "view", "delete"],
        "MusharakahContractRequestQuantity": ["change"],
        "JewelryProduction": ["view", "change"],
        "JewelryProductionProduct": ["change"],
        "JewelryProduct": ["change", "delete", "view"],
        "StoneClarity": ["view"],
        "PreciousItemUnit": ["view"],
        "SettlementSummaryPayment": ["add"],
        "StockManagement": ["view"],
    },
    "Manufacturer": {
        "User": ["change"],
        "Business": ["add", "view", "change", "delete"],
        "Wallet": ["view"],
        "Transaction": ["add", "view"],
        "MusharakahContractRequest": ["view"],
        "JewelryDesign": ["view"],
        "ManufacturingRequest": ["view", "change"],
        "MaterialItem": ["view"],
        "PreciousItems": ["view"],
        "Subscription": ["view"],
        "BankAccount": ["change"],
        "ShareHolder": ["add", "view", "change", "delete"],
        "Currency": ["view"],
        "SubUser": ["add", "view"],
        "ManageUserSuspension": ["change"],
        "OrganizationCurrency": ["view"],
        "OrganizationBankAccount": ["view"],
        "Notification": ["view"],
        "BusinessSavedCards": ["add", "view", "change"],
        "PreciousItemsAttributes": ["view"],
        "ManufacturingEstimationRequest": ["add"],
        "JewelryProduction": ["view", "change"],
        "JewelryProductionProduct": ["change"],
        "StoneClarity": ["view"],
    },
    "Investor": {
        "User": ["change"],
        "Business": ["add", "view", "change", "delete"],
        "PurchaseRequest": ["add", "view", "delete"],
        "Wallet": ["view"],
        "Transaction": ["add", "view"],
        "JewelryDesign": ["view"],
        "MaterialItem": ["view"],
        "PreciousItems": ["view"],
        "Pool": ["view"],
        "PoolContribution": ["add"],
        "MusharakahContract": ["view", "request"],
        "MusharakahContractMaterial": ["view"],
        "MusharakahContractTerminationRequest": ["add", "view", "change", "delete"],
        "Subscription": ["view"],
        "BankAccount": ["change"],
        "ShareHolder": ["add", "view", "change", "delete"],
        "Currency": ["view"],
        "SubUser": ["add", "view"],
        "ManageUserSuspension": ["change"],
        "OrganizationCurrency": ["view"],
        "OrganizationBankAccount": ["view"],
        "Notification": ["view"],
        "BusinessSavedCards": ["add", "view", "change"],
        "PreciousItemsAttributes": ["view"],
        "MusharakahContractRequest": ["view"],
        "MusharakahContractRequestAssetContribution": ["change"],
        "StoneClarity": ["view"],
        "LogisticCostPayment": ["add"],
    },
    "Seller": {
        "User": ["change"],
        "Business": ["add", "view", "change", "delete"],
        "PurchaseRequest": ["view"],
        "Wallet": ["view"],
        "Transaction": ["add", "view"],
        "MaterialItem": ["view"],
        "PreciousItems": ["add", "view", "change", "delete"],
        "Subscription": ["view"],
        "BankAccount": ["change"],
        "ShareHolder": ["add", "view", "change", "delete"],
        "Currency": ["view"],
        "SellerDashboard": ["view"],
        "SubUser": ["add", "view"],
        "ManageUserSuspension": ["change"],
        "OrganizationCurrency": ["view"],
        "OrganizationBankAccount": ["view"],
        "Notification": ["view"],
        "BusinessSavedCards": ["add", "view", "change"],
        "PreciousItemsAttributes": ["view"],
        "StoneClarity": ["view"],
    },
    "Taqabeth Enforcer": {
        "User": ["change"],
        "BusinessList": ["view"],
        "Notification": ["add", "view"],
        "AdminPurchaseRequest": ["view", "change"],
        "MusharakahContractRequest": ["view", "change"],
        "MaterialItem": ["view"],
        "PreciousItems": ["view"],
        "Pool": ["view"],
        "MusharakahContract": ["view"],
        "MusharakahContractMaterial": ["view"],
        "Currency": ["view"],
        "OrganizationCurrency": ["add", "view", "change"],
        "Organization": ["view", "change"],
        "Notification": ["view"],
        "StoneCutShape": ["add", "view", "change"],
        "MetalCaratType": ["add", "view", "change"],
        "StoneClarity": ["add", "view", "change"],
        "Pool": ["add", "view", "change"],
        "PreciousItemsAttributes": ["view"],
        "MusharakahContractRequest": ["view", "change"],
        "JewelryProductType": ["add", "view", "change"],
        "JewelryProductColor": ["add", "view", "change"],
        "MusharakahContractTerminate": ["change"],
        "MusharakahContractTerminationRequest": ["view", "change"],
        "MusharakahContractRenewal": ["add"],
        "TaqabethRequest": ["view"],
        "JewelryProduction": ["view"],
        "OccupiedStock": ["view"],
        "StoneClarity": ["view"],
        "PreciousItemUnit": ["view"],
    },
    "Jewellery Inspector": {
        "User": ["change"],
        "Notification": ["add", "view"],
        "ManufacturingRequest": ["view"],
        "JewelryProduction": ["view", "change"],
        "JewelryProductionProduct": ["change"],
    },
    "Jewellery Buyer": {
        "User": ["change", "view"],
        "MaterialItem": ["view"],
        "BusinessList": ["view"],
        "Wallet": ["view"],
        "Transaction": ["add", "view"],
        "JewelryDesign": ["view"],
        "Subscription": ["view"],
        "PreciousItems": ["view"],
        "Currency": ["view"],
        "OrganizationCurrency": ["add", "view", "change"],
        "Organization": ["view", "change"],
        "Notification": ["view"],
        "StoneCutShape": ["add", "view", "change"],
        "MetalCaratType": ["add", "view", "change"],
        "StoneClarity": ["add", "view", "change"],
        "PreciousItemsAttributes": ["view"],
        "JewelryProductType": ["add", "view", "change"],
        "JewelryProductColor": ["add", "view", "change"],
        "StockManagement": ["view", "change"],
    },
}


# Admins precious item permission
ADMINS_PRECIOUS_ITEM_VIEW_PERMISSION = [{"AdminPreciousItems": ["view"]}]
ADMIN_PURCHASE_REQUEST_CREATE_PERMISSION = [{"AdminCreatePurchaseRequest": ["add"]}]

# Seller Module Permissions
PRECIOUS_ITEM_VIEW_PERMISSION = [{"PreciousItems": ["view"]}]
PRECIOUS_ITEM_CREATE_PERMISSION = [{"PreciousItems": ["add"]}]
PRECIOUS_ITEM_CHANGE_PERMISSION = [{"PreciousItems": ["change"]}]
PRECIOUS_ITEM_DELETE_PERMISSION = [{"PreciousItems": ["delete"]}]
SELLER_DASHBOARD_VIEW_PERMISSION = [{"SellerDashboard": ["view"]}]

# Product Module Permissions
PRODUCT_VIEW_PERMISSION = [{"PreciousItems": ["view"]}]
PURCHASE_REQUEST_VIEW_PERMISSION = [{"PurchaseRequest": ["view"]}]
PURCHASE_REQUEST_CREATE_PERMISSION = [{"PurchaseRequest": ["add"]}]
PURCHASE_REQUEST_DELETE_PERMISSION = [{"PurchaseRequest": ["delete"]}]

BUSINESS_RISK_LEVEL_CHANGE_PERMISSION = [{"BusinessRiskLevel": ["change"]}]

SUBADMIN_CREATE_PERMISSION = [{"SubAdmin": ["add"]}]
SUBADMIN_CHANGE_PERMISSION = [{"SubAdmin": ["change"]}]
SUBADMIN_DELETE_PERMISSION = [{"SubAdmin": ["delete"]}]
SUBADMIN_VIEW_PERMISSION = [{"SubAdmin": ["view"]}]

MATERIAL_ITEM_CREATE_PERMISSION = [{"MaterialItem": ["add"]}]
MATERIAL_ITEM_VIEW_PERMISSION = [{"MaterialItem": ["view"]}]

USER_VIEW_PERMISSION = [{"User": ["view"]}]

BANK_ACCOUNT_CHANGE_PERMISSION = [{"BankAccount": ["change"]}]
USER_PROFILE_CHANGE_PERMISSION = [{"User": ["change"]}]

BUSINESS_VIEW_PERMISSION = [{"Business": ["view"]}]
BUSINESS_CHANGE_PERMISSION = [{"Business": ["change"]}]

BUSINESS_ADMIN_VIEW_PERMISSION = [{"BusinessList": ["view"]}]

SHARE_HOLDER_CREATE_PERMISSION = [{"ShareHolder": ["add"]}]
SHARE_HOLDER_VIEW_PERMISSION = [{"ShareHolder": ["view"]}]
SHARE_HOLDER_CHANGE_PERMISSION = [{"ShareHolder": ["change"]}]
SHARE_HOLDER_DELETE_PERMISSION = [{"ShareHolder": ["delete"]}]

CURRENCY_CREATE_PERMISSION = [{"Currency": ["add"]}]
CURRENCY_VIEW_PERMISSION = [{"Currency": ["view"]}]
CURRENCY_CHANGE_PERMISSION = [{"Currency": ["change"]}]

SUB_USER_CREATE_PERMISSION = [{"SubUser": ["add"]}]
SUB_USER_VIEW_PERMISSION = [{"SubUser": ["view"]}]

ORGANIZATION_CURRENCY_VIEW_PERMISSION = [{"OrganizationCurrency": ["view"]}]
ORGANIZATION_CURRENCY_CREATE_PERMISSION = [{"OrganizationCurrency": ["add"]}]
ORGANIZATION_CURRENCY_CHANGE_PERMISSION = [{"OrganizationCurrency": ["change"]}]

RISK_LEVEL_VIEW_PERMISSION = [{"RiskLevel": ["view"]}]
RISK_LEVEL_CREATE_PERMISSION = [{"RiskLevel": ["add"]}]
RISK_LEVEL_CHANGE_PERMISSION = [{"RiskLevel": ["change"]}]

# Jewelry Design Module Permissions
JEWELRY_DESIGN_VIEW_PERMISSION = [{"JewelryDesign": ["view"]}]
JEWELRY_DESIGN_CREATE_PERMISSION = [{"JewelryDesign": ["add"]}]
JEWELRY_DESIGN_CHANGE_PERMISSION = [{"JewelryDesign": ["change"]}]
JEWELRY_DESIGN_DELETE_PERMISSION = [{"JewelryDesign": ["delete"]}]
JEWELRY_PRODUCT_DELETE_PERMISSION = [{"JewelryProduct": ["delete"]}]
JEWELRY_PRODUCT_CHANGE_PERMISSION = [{"JewelryProduct": ["change"]}]
JEWELRY_PRODUCT_VIEW_PERMISSION = [{"JewelryProduct": ["view"]}]

TRANSACTION_VIEW_PERMISSION = [{"Transaction": ["view"]}]

ORGANIZATION_VIEW_PERMISSION = [{"Organization": ["view"]}]
ORGANIZATION_CHANGE_PERMISSION = [{"Organization": ["change"]}]

ADMIN_PURCHASE_REQUEST_CHANGE_PERMISSION = [{"AdminPurchaseRequest": ["change"]}]
ADMIN_PURCHASE_REQUEST_VIEW_PERMISSION = [{"AdminPurchaseRequest": ["view"]}]

MANAGE_USER_SUSPENSION_CHANGE_PERMISSION = [{"ManageUserSuspension": ["change"]}]
MANAGE_BUSINESS_ACCOUNT_SUSPENSION_CHANGE_PERMISSION = [
    {"ManageBusinessAccountSuspension": ["change"]}
]

ORGANIZATION_BANK_ACCOUNT_CREATE_PERMISSION = [{"OrganizationBankAccount": ["add"]}]
ORGANIZATION_BANK_ACCOUNT_CHANGE_PERMISSION = [{"OrganizationBankAccount": ["change"]}]
ORGANIZATION_BANK_ACCOUNT_VIEW_PERMISSION = [{"OrganizationBankAccount": ["view"]}]

NOTIFICATION_VIEW_PERMISSION = [{"Notification": ["view"]}]

BUSINESS_SAVED_CARDS_VIEW_PERMISSION = [{"BusinessSavedCards": ["view"]}]
BUSINESS_SAVED_CARDS_CREATE_PERMISSION = [{"BusinessSavedCards": ["add"]}]
BUSINESS_SAVED_CARDS_CHANGE_PERMISSION = [{"BusinessSavedCards": ["change"]}]

STONE_CUT_SHAPE_CREATE_PERMISSION = [{"StoneCutShape": ["add"]}]
STONE_CUT_SHAPE_CHANGE_PERMISSION = [{"StoneCutShape": ["change"]}]
STONE_CUT_SHAPE_VIEW_PERMISSION = [{"StoneCutShape": ["view"]}]

METAL_CARAT_TYPE_CREATE_PERMISSION = [{"MetalCaratType": ["add"]}]
METAL_CARAT_TYPE_CHANGE_PERMISSION = [{"MetalCaratType": ["change"]}]
METAL_CARAT_TYPE_VIEW_PERMISSION = [{"MetalCaratType": ["view"]}]

JEWELRY_PRODUCT_TYPE_CREATE_PERMISSION = [{"JewelryProductType": ["add"]}]
JEWELRY_PRODUCT_TYPE_CHANGE_PERMISSION = [{"JewelryProductType": ["change"]}]
JEWELRY_PRODUCT_TYPE_VIEW_PERMISSION = [{"JewelryProductType": ["view"]}]

FUND_STATUS_CREATE_PERMISSION = [{"JewelryProductType": ["add"]}]
FUND_STATUS_CHANGE_PERMISSION = [{"JewelryProductType": ["change"]}]
FUND_STATUS_VIEW_PERMISSION = [{"JewelryProductType": ["view"]}]

EXPECTED_PROFIT_TYPE_CREATE_PERMISSION = [{"JewelryProductType": ["add"]}]
EXPECTED_PROFIT_TYPE_CHANGE_PERMISSION = [{"JewelryProductType": ["change"]}]
EXPECTED_PROFIT_TYPE_VIEW_PERMISSION = [{"JewelryProductType": ["view"]}]

JEWELRY_PRODUCT_COLOR_CREATE_PERMISSION = [{"JewelryProductColor": ["add"]}]
JEWELRY_PRODUCT_COLOR_CHANGE_PERMISSION = [{"JewelryProductColor": ["change"]}]
JEWELRY_PRODUCT_COLOR_VIEW_PERMISSION = [{"JewelryProductColor": ["view"]}]

MUSHARAKAH_DURATION_VIEW_PERMISSION = [{"MusharakahDuration": ["view"]}]
MUSHARAKAH_DURATION_CREATE_PERMISSION = [{"MusharakahDuration": ["add"]}]
MUSHARAKAH_DURATION_CHANGE_PERMISSION = [{"MusharakahDuration": ["change"]}]

PRECIOUS_ITEM_ATTRIBUTES_VIEW_PERMISSION = [{"PreciousItemsAttributes": ["view"]}]

POOL_VIEW_PERMISSION = [{"Pool": ["view"]}]
POOL_CREATE_PERMISSION = [{"Pool": ["add"]}]
POOL_CHANGE_PERMISSION = [{"Pool": ["change"]}]

MUSHARAKAH_CONTRACT_REQUEST_CREATE_PERMISSION = [{"MusharakahContractRequest": ["add"]}]
MUSHARAKAH_CONTRACT_REQUEST_VIEW_PERMISSION = [{"MusharakahContractRequest": ["view"]}]
MUSHARAKAH_CONTRACT_REQUEST_CHANGE_PERMISSION = [
    {"MusharakahContractRequest": ["change"]}
]
MUSHARAKAH_CONTRACT_REQUEST_TERMINATE_CHANGE_PERMISSION = [
    {"MusharakahContractTerminate": ["change"]}
]
MUSHARAKAH_CONTRACT_TERMINATION_REQUEST_VIEW_PERMISSION = [
    {"MusharakahContractTerminationRequest": ["view"]}
]
MUSHARAKAH_CONTRACT_TERMINATION_REQUEST_CHANGE_PERMISSION = [
    {"MusharakahContractTerminationRequest": ["change"]}
]
MUSHARAKAH_CONTRACT_RENEWAL_CREATE_PERMISSION = [{"MusharakahContractRenewal": ["add"]}]
MUSHARAKAH_CONTRACT_REQUEST_ASSET_CONTRIBUTION_CHANGE_PERMISSION = [
    {"MusharakahContractRequestAssetContribution": ["change"]}
]

POOL_CONTRIBUTION_CREATE_PERMISSION = [{"PoolContribution": ["add"]}]

MUSHARAKAH_CONTRACT_REQUEST_QUANTITY_CHANGE_PERMISSION = [
    {"MusharakahContractRequestQuantity": ["change"]}
]
MUSHARAKAH_CONTRACT_TERMINATION_REQUEST_CREATE_PERMISSION = [
    {"MusharakahContractTerminationRequest": ["add"]}
]
SETTLEMENT_SUMMARY_PAYMENT_PERMISSION = [{"SettlementSummaryPayment": ["add"]}]
LOGISTIC_COST_PAYMENT_PERMISSION = [{"LogisticCostPayment": ["add"]}]

MANUFACTURING_REQUEST_CREATE_PERMISSION = [{"ManufacturingRequest": ["add"]}]
MANUFACTURING_REQUEST_VIEW_PERMISSION = [{"ManufacturingRequest": ["view"]}]
MANUFACTURER_BUSINESS_VIEW_PERMISSION = [{"ManufacturerBusiness": ["view"]}]

MANUFACTURING_REQUEST_ESTIMATION_CREATE_PERMISSION = [
    {"ManufacturingEstimationRequest": ["add"]}
]
JEWELRY_PRODUCTION_VIEW_PERMISSION = [{"JewelryProduction": ["view"]}]
JEWELRY_PRODUCTION_CHANGE_PERMISSION = [{"JewelryProduction": ["change"]}]
JEWELRY_PRODUCTION_PRODUCT_CHANGE_PERMISSION = [
    {"JewelryProductionProduct": ["change"]}
]

TAQABETH_REQUEST_VIEW_PERMISSION = [{"TaqabethRequest": ["view"]}]
OCCUPIED_STOCK_VIEW_PERMISSION = [{"OccupiedStock": ["view"]}]

STONE_CLARITY_CREATE_PERMISSION = [{"StoneClarity": ["add"]}]
STONE_CLARITY_VIEW_PERMISSION = [{"StoneClarity": ["view"]}]
STONE_CLARITY_CHANGE_PERMISSION = [{"StoneClarity": ["change"]}]

PRECIOUS_ITEM_UNIT_VIEW_PERMISSION = [{"PreciousItemUnit": ["view"]}]

# Business Subscription Plan Module Permissions
BUSINESS_SUBSCRIPTION_CHANGE_PERMISSION = [{"Subscription": ["change"]}]
# Jewelry Buyer Permissions
STOCK_MANAGEMENT_VIEW_PERMISSION = [{"StockManagement": ["view"]}]
STOCK_MANAGEMENT_UPDATE_PERMISSION = [{"StockManagement": ["change"]}]
