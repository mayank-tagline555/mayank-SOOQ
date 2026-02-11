from django.urls import path

from .views import PreciousItemListCreateView
from .views import PreciousItemReportNumberExistsAPIView
from .views import PreciousItemRetrieveUpdateDeleteView
from .views import PurchaseRequestListView
from .views import SaleRequestSetDeductionAmountView
from .views import SalesByContinentApiView
from .views import SellerDashboardApiView
from .views import UpdatePurchaseRequestStatusView

urlpatterns = [
    # PurchaseRequest URLs
    path(
        "requests/precious-item/<str:pk>/",
        UpdatePurchaseRequestStatusView.as_view(),
        name="request-precious-item-list",
    ),
    path(
        "requests/precious-item/sale/<str:pk>/deduction/",
        SaleRequestSetDeductionAmountView.as_view(),
        name="sale-request-set-deduction-amount",
    ),
    path(
        "requests/precious-item/",
        PurchaseRequestListView.as_view(),
        name="request-precious-item-list",
    ),
    # PreciousItem URLs
    path(
        "precious-items/<str:pk>/",
        PreciousItemRetrieveUpdateDeleteView.as_view(),
        name="precious-items-retrieve-update-delete",
    ),
    path(
        "precious-items/",
        PreciousItemListCreateView.as_view(),
        name="precious-items-list-create",
    ),
    path(
        "dashboard/",
        SellerDashboardApiView.as_view(),
        name="dashboard",
    ),
    path(
        "dashboard/demographic/",
        SalesByContinentApiView.as_view(),
        name="dashboard-demographic",
    ),
    path(
        "precious-item/report-number/validate/",
        PreciousItemReportNumberExistsAPIView.as_view(),
        name="precious-item-report-number-validate",
    ),
]
