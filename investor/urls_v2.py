from django.urls import path

from investor.views.purchase_request import PurchaseRequestCreateViewV2

urlpatterns = [
    path(
        "requests/precious-item/purchase/",
        PurchaseRequestCreateViewV2.as_view(),
        name="precious-item-request-create-v2",
    ),
]
