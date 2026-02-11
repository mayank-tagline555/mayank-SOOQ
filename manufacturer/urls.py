from django.urls import path

from manufacturer.views import manufacturing_requests
from manufacturer.views import production_hub

urlpatterns = [
    path(
        "requests/manufacturing-estimation/",
        manufacturing_requests.ManufacturingEstimationRequestCreateAPIView.as_view(),
        name="jewelry-manufacturing-estimation-request-create",
    ),
    path(
        "requests/manufacturing-estimations/",
        manufacturing_requests.EstimationManufacturingListAPIView.as_view(),
        name="estimation-manufacturing-requests-list",
    ),
    path(
        "requests/manufacturing/",
        manufacturing_requests.ManufacturingRequestListAPIView.as_view(),
        name="manufacturing-requests-list",
    ),
    path(
        "requests/manufacturing/correction-value/",
        manufacturing_requests.CorrectionValueCreateAPIView.as_view(),
        name="correction-value-create",
    ),
    path(
        "requests/manufacturing/<str:pk>/",
        manufacturing_requests.ManufacturingRequestRetrieveAPIView.as_view(),
        name="manufacturing-request-retrieve",
    ),
    path(
        "jewelry/productions/",
        production_hub.JewelryProductionListAPIView.as_view(),
        name="jewelry-productions-list",
    ),
    path(
        "jewelry/productions/<str:pk>/",
        production_hub.JewelryProductionUpdateRetrieveAPIView.as_view(),
        name="jewelry-production-retrieve-update",
    ),
    path(
        "jewelry/productions/products/<str:pk>/status/",
        production_hub.JewelryProductStatusUpdateAPIView.as_view(),
        name="jewelry-product-status-update",
    ),
    path(
        "dashboard/",
        manufacturing_requests.ManufacturerDashboardAPIView.as_view(),
        name="dashboard",
    ),
    path(
        "jewelry-product/stone-price/",
        production_hub.JewelryProductStonePriceCreateAPIView.as_view(),
        name="jewelry-product-stone-price-create",
    ),
]
