from django.urls import include
from django.urls import path
from rest_framework.routers import DefaultRouter

from investor.views.purchase_request import AdminPurchaseRequestCreateView
from seller.views import AdminPreciousItemListView
from sooq_althahab_admin.sub_admin_views.jewelry_buyer import (
    JewelryBuyerDashboardAPIView,
)
from sooq_althahab_admin.sub_admin_views.jewelry_buyer import (
    JewelryProductMarketplaceCreateAPIView,
)
from sooq_althahab_admin.sub_admin_views.jewelry_buyer import (
    JewelryProductMarketplaceListAPIView,
)
from sooq_althahab_admin.sub_admin_views.jewelry_buyer import JewelrySaleCreateAPIView
from sooq_althahab_admin.sub_admin_views.jewelry_buyer import JewelrySaleListAPIView
from sooq_althahab_admin.sub_admin_views.jewelry_buyer import (
    JewelrySaleRetrieveUpdateAPIView,
)
from sooq_althahab_admin.sub_admin_views.jewelry_buyer import JewelryStockListAPIView
from sooq_althahab_admin.sub_admin_views.jewelry_buyer import (
    JewelryStockRetrieveAPIView,
)
from sooq_althahab_admin.sub_admin_views.jewelry_buyer import JewelryStockUpdateAPIView
from sooq_althahab_admin.sub_admin_views.jewelry_buyer import StockListAPIView
from sooq_althahab_admin.sub_admin_views.jewelry_buyer import StockRetrieveAPIView
from sooq_althahab_admin.sub_admin_views.jewelry_inspector import (
    JewelryInspectorDashboardAPIView,
)
from sooq_althahab_admin.sub_admin_views.jewelry_inspector import (
    JewelryProductionDeliveryStatusAPIView,
)
from sooq_althahab_admin.sub_admin_views.jewelry_inspector import (
    JewelryProductionInspectionListAPIView,
)
from sooq_althahab_admin.sub_admin_views.jewelry_inspector import (
    JewelryProductionInspectionRetriveAPIView,
)
from sooq_althahab_admin.sub_admin_views.jewelry_inspector import (
    JewelryProductionInspectionStatusUpdateAPIView,
)
from sooq_althahab_admin.sub_admin_views.jewelry_inspector import (
    JewelryProductionProductCommentUpdateAPIView,
)
from sooq_althahab_admin.sub_admin_views.jewelry_inspector import (
    JewelryProductionProductInspectionStatusUpdateAPIView,
)
from sooq_althahab_admin.sub_admin_views.taqabeth_enforcer import (
    OccupiedStockListAPIView,
)
from sooq_althahab_admin.sub_admin_views.taqabeth_enforcer import (
    OccupiedStockRetrieveAPIView,
)
from sooq_althahab_admin.sub_admin_views.taqabeth_enforcer import (
    TaqabethEnfocerDashboardAPIView,
)
from sooq_althahab_admin.sub_admin_views.taqabeth_enforcer import (
    TaqabethRequestListAPIView,
)
from sooq_althahab_admin.views import AdminBusinessRiskLevelUpdateAPIView
from sooq_althahab_admin.views import (
    AdminMusharakahContractTerminationRequestCreateAPIView,
)
from sooq_althahab_admin.views import AdminPurchaseRequestUpdateAPIView
from sooq_althahab_admin.views import BusinessAccountSuspensionUpdateAPIView
from sooq_althahab_admin.views import BusinessDeleteAPIView
from sooq_althahab_admin.views import BusinessListAPIView
from sooq_althahab_admin.views import BusinessSubscriptionPlanRetrieveAdminAPIView
from sooq_althahab_admin.views import GlobalMetalListAPIView
from sooq_althahab_admin.views import InvestorListAPIView
from sooq_althahab_admin.views import JewelryProductColorListCreateAPIView
from sooq_althahab_admin.views import JewelryProductColorRetrieveUpdateAPIView
from sooq_althahab_admin.views import JewelryProductTypeListCreateAPIView
from sooq_althahab_admin.views import JewelryProductTypeRetrieveUpdateAPIView
from sooq_althahab_admin.views import JewelryProfitDistributionDetailView
from sooq_althahab_admin.views import JewelryProfitDistributionListView
from sooq_althahab_admin.views import ManufacturingRequestDetailsAPIView
from sooq_althahab_admin.views import ManufacturingRequestListView
from sooq_althahab_admin.views import MaterialItemListCreateAPIView
from sooq_althahab_admin.views import MaterialItemUpdateViewSet
from sooq_althahab_admin.views import MetalCaratTypeListCreateAPIView
from sooq_althahab_admin.views import MetalCaratTypeRetrieveUpdateAPIView
from sooq_althahab_admin.views import MusharakahContractManufacturingCostAPIView
from sooq_althahab_admin.views import MusharakahContractRenewalCreateAPIView
from sooq_althahab_admin.views import (
    MusharakahContractRequestFromTerminatedCreateAPIView,
)
from sooq_althahab_admin.views import MusharakahContractRequestListAPIView
from sooq_althahab_admin.views import MusharakahContractRequestPreApprovalAPIView
from sooq_althahab_admin.views import MusharakahContractRequestRetrieveAPIView
from sooq_althahab_admin.views import MusharakahContractRequestStatusUpdateAPIView
from sooq_althahab_admin.views import MusharakahContractRequestTerminationUpdateAPIView
from sooq_althahab_admin.views import MusharakahContractTerminationRequestListAPIView
from sooq_althahab_admin.views import (
    MusharakahContractTerminationRequestStatusUpdateAPIView,
)
from sooq_althahab_admin.views import MusharakahDurationChoiceListCreateAPIView
from sooq_althahab_admin.views import MusharakahDurationChoiceRetrieveUpdateAPIView
from sooq_althahab_admin.views import OrganizationBankAccountCreateRetrieveUpdateAPIView
from sooq_althahab_admin.views import OrganizationCurrencyCreateView
from sooq_althahab_admin.views import OrganizationCurrencyUpdateView
from sooq_althahab_admin.views import OrganizationRetrieveUpdateViewSet
from sooq_althahab_admin.views import OrganizationRiskLevelListCreateAPIView
from sooq_althahab_admin.views import OrganizationRiskLevelRetrieveUpdateAPIView
from sooq_althahab_admin.views import PoolContributionUpdateAPIView
from sooq_althahab_admin.views import PoolListCreateAPIView
from sooq_althahab_admin.views import PoolRetrieveUpdateAPIView
from sooq_althahab_admin.views import PreciousItemAttributesAPIView
from sooq_althahab_admin.views import PreciousItemUnitAPIView
from sooq_althahab_admin.views import PreciousItemUnitUpdateView
from sooq_althahab_admin.views import PurchaseRequestListAPIView
from sooq_althahab_admin.views import PurchaseRequestRetrieveAPIView
from sooq_althahab_admin.views import StoneClarityListCreateAPIView
from sooq_althahab_admin.views import StoneClarityRetrieveUpdateAPIView
from sooq_althahab_admin.views import StoneCutShapeListCreateAPIView
from sooq_althahab_admin.views import StoneCutShapeRetrieveUpdateAPIView
from sooq_althahab_admin.views import SubAdminViewSet
from sooq_althahab_admin.views import SubscriptionPlanListCreateAPIView
from sooq_althahab_admin.views import SubscriptionPlanRetrieveUpdateDeleteAPIView
from sooq_althahab_admin.views import SubscriptionTransactionListAdminAPIView
from sooq_althahab_admin.views import SubscriptionTransactionRetrieveAdminAPIView
from sooq_althahab_admin.views import ToggleSubscriptionPlanStatusAPIView
from sooq_althahab_admin.views import TransactionListAdminAPIView
from sooq_althahab_admin.views import TransactionRetrieveAdminAPIView
from sooq_althahab_admin.views import UserListAPIView
from sooq_althahab_admin.views import UserRetrieveAPIView
from sooq_althahab_admin.views import UserSuspensionStatusUpdateAPIView
from sooq_althahab_admin.views import WalletTransactionsStatusApproveRejectUpdateAPIView

router = DefaultRouter()

router.register(r"sub-admins", SubAdminViewSet, basename="sub-admins")
urlpatterns = [
    path("", include(router.urls)),
    path(
        "subscription-plans/",
        SubscriptionPlanListCreateAPIView.as_view(),
        name="subscription-plan-list-create",
    ),
    path(
        "subscription-plans/<str:pk>/",
        SubscriptionPlanRetrieveUpdateDeleteAPIView.as_view(),
        name="subscription-plan-detail",
    ),
    path(
        "subscription-plans/<str:pk>/status/update/",
        ToggleSubscriptionPlanStatusAPIView.as_view(),
        name="subscription-plan-toggle-status",
    ),
    path("users/", UserListAPIView.as_view(), name="users-list"),
    path("businesses/", BusinessListAPIView.as_view(), name="businesses-list"),
    path("investors/", InvestorListAPIView.as_view(), name="investors-list"),
    path(
        "business/<str:pk>/",
        BusinessDeleteAPIView.as_view(),
        name="businesses-delete",
    ),
    path("users/<str:pk>/", UserRetrieveAPIView.as_view(), name="user-retrieve"),
    path(
        "material-items/", MaterialItemListCreateAPIView.as_view(), name="material_type"
    ),
    path("global-metal/", GlobalMetalListAPIView.as_view(), name="global_metal"),
    path(
        "user/<str:pk>/suspension/",
        UserSuspensionStatusUpdateAPIView.as_view(),
        name="user-suspension-update",
    ),
    path(
        "business/subscription/<str:pk>/",
        BusinessSubscriptionPlanRetrieveAdminAPIView.as_view(),
        name="business-subscription-plan-retrieve",
    ),
    path(
        "business/<str:pk>/update-risk-level/",
        AdminBusinessRiskLevelUpdateAPIView.as_view(),
        name="admin-update-business-risk-level",
    ),
    path(
        "requests/precious-item/",
        PurchaseRequestListAPIView.as_view(),
        name="precious-item-requests",
    ),
    path(
        "organization/",
        OrganizationRetrieveUpdateViewSet.as_view(),
        name="organization-taxes-and-fees-update",
    ),
    path(
        "material-item/<str:pk>",
        MaterialItemUpdateViewSet.as_view(),
        name="material-item-update",
    ),
    path(
        "requests/precious-item/<str:pk>/",
        PurchaseRequestRetrieveAPIView.as_view(),
        name="precious-item-request-retrieve-update",
    ),
    path(
        "organization-currency/",
        OrganizationCurrencyCreateView.as_view(),
        name="organization-currency-create",
    ),
    path(
        "transactions/",
        TransactionListAdminAPIView.as_view(),
        name="transactions-list",
    ),
    path(
        "transaction/<str:pk>/",
        TransactionRetrieveAdminAPIView.as_view(),
        name="transactions-retrieve",
    ),
    path(
        "subscription-transactions/",
        SubscriptionTransactionListAdminAPIView.as_view(),
        name="subscription-transactions-list",
    ),
    path(
        "subscription-transaction/<str:pk>/",
        SubscriptionTransactionRetrieveAdminAPIView.as_view(),
        name="subscription-transactions-retrieve",
    ),
    path(
        "requests/precious-item/complete/<str:id>/",
        AdminPurchaseRequestUpdateAPIView.as_view(),
        name="precious-item-request-complete-update",
    ),
    path(
        "organization-currency/<str:pk>/",
        OrganizationCurrencyUpdateView.as_view(),
        name="organization-currency-update",
    ),
    path(
        "risk-level/",
        OrganizationRiskLevelListCreateAPIView.as_view(),
        name="organization-risk-level-create",
    ),
    path(
        "risk-level/<str:pk>/",
        OrganizationRiskLevelRetrieveUpdateAPIView.as_view(),
        name="organization-risk-level-retrieve-update",
    ),
    path(
        "wallet/transactions/<str:pk>/approve-reject/",
        WalletTransactionsStatusApproveRejectUpdateAPIView.as_view(),
        name="wallet-transactions-status-approve-reject-update",
    ),
    path(
        "organization/bank-account/",
        OrganizationBankAccountCreateRetrieveUpdateAPIView.as_view(),
        name="organization-bank-account-create",
    ),
    path(
        "business/<str:pk>/suspension/",
        BusinessAccountSuspensionUpdateAPIView.as_view(),
        name="business-suspension-update",
    ),
    path(
        "stone-cut-shape/",
        StoneCutShapeListCreateAPIView.as_view(),
        name="stone-cut-shape-list-create",
    ),
    path(
        "stone-cut-shape/<str:pk>/",
        StoneCutShapeRetrieveUpdateAPIView.as_view(),
        name="stone-cut-shape-retrieve-update",
    ),
    path(
        "stone-clarity/",
        StoneClarityListCreateAPIView.as_view(),
        name="stone-clarity-list-create",
    ),
    path(
        "stone-clarity/<str:pk>/",
        StoneClarityRetrieveUpdateAPIView.as_view(),
        name="stone-clarity-retrieve-update",
    ),
    path(
        "metal-carat-type/",
        MetalCaratTypeListCreateAPIView.as_view(),
        name="metal-carat-type-create-list",
    ),
    path(
        "metal-carat-type/<str:pk>/",
        MetalCaratTypeRetrieveUpdateAPIView.as_view(),
        name="metal-carat-type-retrieve-update",
    ),
    path(
        "jewelry/product-type/",
        JewelryProductTypeListCreateAPIView.as_view(),
        name="jewelry-product-type-list-create",
    ),
    path(
        "jewelry/product-type/<str:pk>/",
        JewelryProductTypeRetrieveUpdateAPIView.as_view(),
        name="jewelry-product-type-retrieve-update",
    ),
    path(
        "jewelry/product-color/",
        JewelryProductColorListCreateAPIView.as_view(),
        name="jewelry-product-color-list-create",
    ),
    path(
        "jewelry/product-color/<str:pk>/",
        JewelryProductColorRetrieveUpdateAPIView.as_view(),
        name="jewelry-product-retrieve-update",
    ),
    path(
        "precious-item/attributes/",
        PreciousItemAttributesAPIView.as_view(),
        name="precious-item-attributes-list",
    ),
    path("pool/", PoolListCreateAPIView.as_view(), name="pool-list-create"),
    path(
        "pool/<str:pk>/",
        PoolRetrieveUpdateAPIView.as_view(),
        name="pool-retrieve-update",
    ),
    path(
        "pool/contributor/<str:pk>/update/",
        PoolContributionUpdateAPIView.as_view(),
        name="pool-contributor-update",
    ),
    path(
        "request/musharakah-contract/replacement/",
        MusharakahContractRequestFromTerminatedCreateAPIView.as_view(),
        name="musharakah-contract-request-replacement-create",
    ),
    path(
        "request/musharakah-contract/",
        MusharakahContractRequestListAPIView.as_view(),
        name="musharakah-contract-request-list",
    ),
    path(
        "request/musharakah-contract/termination/",
        MusharakahContractTerminationRequestListAPIView.as_view(),
        name="musharakah-contract-terminate-request-list",
    ),
    path(
        "request/musharakah-contract/renew/",
        MusharakahContractRenewalCreateAPIView.as_view(),
        name="musharakah-contract-request-renew-create",
    ),
    path(
        "request/musharakah-contract/<str:pk>/",
        MusharakahContractRequestRetrieveAPIView.as_view(),
        name="musharakah-contract-request-retrieve",
    ),
    path(
        "request/musharakah-contract/admin-approval/<str:pk>/",
        MusharakahContractRequestPreApprovalAPIView.as_view(),
        name="musharakah-contract-request-admin-approval",
    ),
    path(
        "request/musharakah-contract/status/<str:pk>/",
        MusharakahContractRequestStatusUpdateAPIView.as_view(),
        name="musharakah-contract-request-status-update",
    ),
    path(
        "request/musharakah-contract/terminate/<str:pk>/",
        MusharakahContractRequestTerminationUpdateAPIView.as_view(),
        name="musharakah-contract-request-terminate-update",
    ),
    path(
        "request/musharakah-contract/termination/<str:pk>/status/",
        MusharakahContractTerminationRequestStatusUpdateAPIView.as_view(),
        name="musharakah-contract-termination-request-status-update",
    ),
    path(
        "musharakah-duration-choices/",
        MusharakahDurationChoiceListCreateAPIView.as_view(),
        name="musharakah-duration-list-create",
    ),
    path(
        "musharakah-duration-choices/<str:pk>/",
        MusharakahDurationChoiceRetrieveUpdateAPIView.as_view(),
        name="musharakah-duration-retrieve-update",
    ),
    path(
        "requests/manufacturing/",
        ManufacturingRequestListView.as_view(),
        name="manufacturing-requests-list",
    ),
    path(
        "requests/manufacturing/<str:pk>/",
        ManufacturingRequestDetailsAPIView.as_view(),
        name="manufacturing-request-retrieve",
    ),
    path(
        "jewelry/inspections/",
        JewelryProductionInspectionListAPIView.as_view(),
        name="jewelry-production-inspection-list",
    ),
    path(
        "jewelry/inspections/<str:pk>/",
        JewelryProductionInspectionRetriveAPIView.as_view(),
        name="jewelry-production-inspection-retrieve",
    ),
    path(
        "jewelry/inspections/<str:pk>/status/",
        JewelryProductionInspectionStatusUpdateAPIView.as_view(),
        name="jewelry-production-inspection-status-update",
    ),
    path(
        "jewelry/product/inspections/<str:pk>/status/",
        JewelryProductionProductInspectionStatusUpdateAPIView.as_view(),
        name="jewelry-production-inspection-status-update",
    ),
    path(
        "jewelry-production/<str:pk>/delivery-status/",
        JewelryProductionDeliveryStatusAPIView.as_view(),
        name="jewelry-production-delivery-status",
    ),
    path(
        "jewelry-production/product/<str:pk>/",
        JewelryProductionProductCommentUpdateAPIView.as_view(),
        name="jewelry-production-product-update",
    ),
    path(
        "jewelry-inspector/dashboard/",
        JewelryInspectorDashboardAPIView.as_view(),
        name="jewelry-inspector-dashboard-list",
    ),
    # Legacy endpoints (for backward compatibility)
    path("jewelry-buyer/stocks/", StockListAPIView.as_view(), name="stocks-list"),
    path(
        "jewelry-buyer/stock/<str:pk>/",
        StockRetrieveAPIView.as_view(),
        name="stock-detail",
    ),
    # New Stock Management endpoints
    path(
        "jewelry-buyer/stock-management/",
        JewelryStockListAPIView.as_view(),
        name="jewelry-stock-list",
    ),
    path(
        "jewelry-buyer/stock-management/<str:pk>/",
        JewelryStockRetrieveAPIView.as_view(),
        name="jewelry-stock-retrieve",
    ),
    path(
        "jewelry-buyer/stock-management/<str:pk>/update/",
        JewelryStockUpdateAPIView.as_view(),
        name="jewelry-stock-update",
    ),
    # Marketplace endpoints
    path(
        "jewelry-buyer/marketplace/",
        JewelryProductMarketplaceListAPIView.as_view(),
        name="jewelry-product-marketplace-list",
    ),
    path(
        "jewelry-buyer/marketplace/publish/",
        JewelryProductMarketplaceCreateAPIView.as_view(),
        name="jewelry-product-marketplace-create",
    ),
    # Dashboard endpoint
    path(
        "jewelry-buyer/dashboard/",
        JewelryBuyerDashboardAPIView.as_view(),
        name="jewelry-buyer-dashboard",
    ),
    # Sales Management URLs
    path(
        "jewelry-buyer/sales/",
        JewelrySaleListAPIView.as_view(),
        name="jewelry-sales-list",
    ),
    path(
        "jewelry-buyer/sales/create/",
        JewelrySaleCreateAPIView.as_view(),
        name="jewelry-sales-create",
    ),
    path(
        "jewelry-buyer/sales/<str:pk>/",
        JewelrySaleRetrieveUpdateAPIView.as_view(),
        name="jewelry-sales-retrieve",
    ),
    path(
        "taqabeth-enforcer/requests/",
        TaqabethRequestListAPIView.as_view(),
        name="taqabeth-request-list",
    ),
    path(
        "taqabeth-enforcer/stocks/occupied/",
        OccupiedStockListAPIView.as_view(),
        name="occupied-stock-list",
    ),
    path(
        "taqabeth-enforcer/stocks/occupied/<str:pk>/",
        OccupiedStockRetrieveAPIView.as_view(),
        name="occupied-stock-retrieve",
    ),
    path(
        "taqabeth-enforcer/dashboard/",
        TaqabethEnfocerDashboardAPIView.as_view(),
        name="taqabeth-dashboard",
    ),
    path(
        "precious-items/",
        AdminPreciousItemListView.as_view(),
        name="admins-precious-items-list",
    ),
    path(
        "purchase-request/assign-precious-item/",
        AdminPurchaseRequestCreateView.as_view(),
        name="admins-assign-precious-items-to-investor",
    ),
    path(
        "precious-item/units/",
        PreciousItemUnitAPIView.as_view(),
        name="precious-item-units-list",
    ),
    path(
        "precious-item/units/<str:pk>/",
        PreciousItemUnitUpdateView.as_view(),
        name="precious-item-units-list",
    ),
    path(
        "musharakah-contract/manufacturing-cost/",
        MusharakahContractManufacturingCostAPIView.as_view(),
        name="musharakah-contract-manufacturing-cost",
    ),
    path(
        "requests/musharakah-contracts/terminate-request/",
        AdminMusharakahContractTerminationRequestCreateAPIView.as_view(),
        name="musharakah-contract-terminate-requests-create",
    ),
    path("profit-distribution/", JewelryProfitDistributionListView.as_view()),
    path(
        "profit-distribution/<str:pk>/", JewelryProfitDistributionDetailView.as_view()
    ),
]
