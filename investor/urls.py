from django.urls import path

from investor.views import asset_contribution
from investor.views import musharakah_contract_request
from investor.views import pool
from investor.views import purchase_request
from jeweler.views.musharakah_contract_request import (
    MusharakahContractTerminationRequestCreateAPIView,
)

urlpatterns = [
    # Endpoint for validating serial numbers and system serial numbers
    # Checks before bulk updates or actual operations
    path(
        "precious-item-units/validate-serial-number/",
        purchase_request.SerialNumberValidationAPIView.as_view(),
        name="validate-serial-number",
    ),
    # Endpoint for investors to request the sale of their previously purchased assets.
    path(
        "requests/precious-item/sale/",
        purchase_request.SaleRequestCreateView.as_view(),
        name="my-assets-sale",
    ),
    # Endpoint for investors to approve/reject sale requests with proposed price.
    path(
        "requests/precious-item/sale/<str:pk>/confirm/",
        purchase_request.SaleRequestConfirmationView.as_view(),
        name="sale-request-confirmation",
    ),
    path(
        # Investor creates purchase request
        # to buy precious items from a seller or refinery.
        "requests/precious-item/purchase/",
        purchase_request.PurchaseRequestCreateView.as_view(),
        name="precious-item-request-create",
    ),
    path(
        "requests/precious-item/",
        purchase_request.PurchaseRequestListView.as_view(),
        name="precious-item-request-lists",
    ),
    # Endpoint for investors to view all pending purchase and sale requests
    # Shows all requests with status: PENDING, PENDING_SELLER_PRICE, PENDING_INVESTOR_CONFIRMATION
    path(
        "requests/precious-item/pending/",
        purchase_request.PendingPurchaseRequestListView.as_view(),
        name="pending-purchase-request-lists",
    ),
    # Retrived filtered data for musharakah request material
    path(
        "purchase-requests/available-assets/",
        purchase_request.AvailableAssetPurchaseRequestAPIView.as_view(),
        name="filtered-purchase-request-list",
    ),
    # Retrieves purchase request for purchased - Rejected and Sales request for Approved(Sold) assets.
    path(
        "requests/precious-item/history/",
        purchase_request.PortfolioHistoryAPIView.as_view(),
        name="precious-item-request-history",
    ),
    path(
        "requests/precious-item/<str:pk>/",
        purchase_request.PurchaseRequestRetrieveDeleteView.as_view(),
        name="precious-item-request-retrieve-delete",
    ),
    path(
        "my-assets/profit/",
        purchase_request.RealizedProfitView.as_view(),
        name="my-assets-profit",
    ),
    # Retrieves asset statistics, including request counts and a material-wise summary.
    path(
        "my-assets/summary/",
        purchase_request.MyAssetsView.as_view(),
        name="my-assets-summary",
    ),
    path(
        "pools/",
        pool.PoolListAPIView.as_view(),
        name="pools-list",
    ),
    path(
        "pools/contribution/",
        pool.PoolContributionListCreateAPIView.as_view(),
        name="pool-contribution-create",
    ),
    path(
        "pools/summary/",
        pool.PoolSummaryAPIView.as_view(),
        name="pools-summary",
    ),
    path(
        "pools/<str:pk>/",
        pool.PoolRetriveAPIView.as_view(),
        name="pools-retrieve",
    ),
    path(
        "musharakah-contract/contributions/",
        musharakah_contract_request.MusharakahContractRequestAPIView.as_view(),
        name="musharakah-contract-contributions-list",
    ),
    path(
        "musharakah-contract/termination/logistic-cost/payment/",
        musharakah_contract_request.LogisticCostPaymentCreateAPI.as_view(),
        name="musharakah-contract-termination-logistic-cost-payment",
    ),
    path(
        "musharakah-contract/termination/refining-cost/payment/",
        musharakah_contract_request.RefiningCostPaymentCreateAPI.as_view(),
        name="musharakah-contract-termination-refining-cost-payment",
    ),
    path(
        "musharakah-contract/early-termination/payment/",
        musharakah_contract_request.MusharakahContractEarlyTerminationPaymentCreateAPIView.as_view(),
        name="musharakah-contract-early-termination-payment",
    ),
    path(
        "requests/musharakah-contract/",
        musharakah_contract_request.MusharakahContractRequestListViewAPIView.as_view(),
        name="musharakah-contract-request-list",
    ),
    path(
        "requests/musharakah-contract/summary/",
        musharakah_contract_request.MusharakahContractRequestSummaryAPIView.as_view(),
        name="musharakah-contract-request-summary",
    ),
    path(
        "requests/musharakah-contract/profit/",
        musharakah_contract_request.MusharakahContractProfitAPIView.as_view(),
        name="musharakah-contract-profit",
    ),
    path(
        "requests/musharakah-contract/<str:pk>/",
        musharakah_contract_request.MusharakahContractRequestRetriveAPIView.as_view(),
        name="musharakah-contract-request-retrieve",
    ),
    path(
        "requests/musharakah-contract/<str:pk>/asset-contribution/",
        musharakah_contract_request.MusharakahContractRequestAssetContributionUpdateAPIView.as_view(),
        name="musharakah-contract-request-asset-contribution-update",
    ),
    path(
        "requests/musharakah-contract/<str:pk>/agreement/",
        musharakah_contract_request.MusharakahContractAgreementAPIView.as_view(),
        name="musharakah-contract-agreement",
    ),
    path(
        "pool/<str:pk>/download",
        pool.PoolDownloadAPIView.as_view(),
        name="pool-download",
    ),
    path(
        "asset-contributions/",
        asset_contribution.AssetContributionListView.as_view(),
        name="asset-contribution-list",
    ),
    path(
        "requests/musharakah-contracts/terminate-request/",
        MusharakahContractTerminationRequestCreateAPIView.as_view(),
        name="musharakah-contract-terminate-requests-create",
    ),
]
