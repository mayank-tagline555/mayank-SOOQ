"""
URL configuration for sooq_althahab project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include
from django.urls import path
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions
from rest_framework import status

from account.views import CheckVersionView
from account.views import OrganizationFeesTaxesAPIView
from investor.views import product
from investor.views import wallet
from sooq_althahab.payment_gateway_services.benefit import benefit
from sooq_althahab.payment_gateway_services.credimax.hosted_checkout import checkout
from sooq_althahab.payment_gateway_services.credimax.subscription import apis
from sooq_althahab.payment_gateway_services.credimax.subscription.views.cancel_business_subscription_api import (
    CancelBusinessSubscriptionPlanAPIView,
)
from sooq_althahab.payment_gateway_services.credimax.subscription.views.retry_billing_api import (
    RetryBillingDetailsAndMailAPIView,
)
from sooq_althahab.payment_gateway_services.credimax.subscription.views.suspend_business_subscription_api import (
    SuspendBusinessSubscriptionPlanAPIView,
)
from sooq_althahab.payment_gateway_services.credimax.subscription.views.test_recurring_payment_api import (
    TestProRataRecurringPaymentAPIView,
)
from sooq_althahab.payment_gateway_services.credimax.subscription.views.test_recurring_payment_api import (
    TestSubscriptionFeeRecurringPaymentAPIView,
)
from sooq_althahab.payment_gateway_services.credimax.subscription.views.update_business_subscription_api import (
    UpdateBusinessSubscriptionPlanAPIView,
)
from sooq_althahab.utils import build_error_response
from sooq_althahab.views import GeneratePresignedS3URLAPIView
from sooq_althahab.views import PreciousMetalPriceListAPIView

from .webhook import ShuftiWebhookView

schema_view = get_schema_view(
    openapi.Info(
        title="Sooq Al Thahab API",
        default_version="v1",
        # TODO: Add the following details once available.
        # description="APIs provided by Sooq Al Thahab.",
        # terms_of_service="https://www.google.com/policies/terms/",
        # contact=openapi.Contact(email="contact@snippets.local"),
        # license=openapi.License(name="BSD License"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)


def custom_page_not_found(request, exception=None):
    return build_error_response(
        "NotFound",
        f"The requested URL {request.path} was not found.",
        status.HTTP_404_NOT_FOUND,
        use_drf=False,
    )


def custom_server_error(request):
    return build_error_response(
        "ServerError",
        "Something went wrong on the server.",
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        use_drf=False,
    )


def custom_permission_denied(request, exception=None):
    return build_error_response(
        "PermissionDenied",
        "You do not have permission to perform this action.",
        status.HTTP_403_FORBIDDEN,
        use_drf=False,
    )


handler404 = custom_page_not_found
handler500 = custom_server_error
handler403 = custom_permission_denied


# Health check view
def health_check(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("", health_check, name="health_check"),  # Root endpoint
    path(
        "swagger<format>/", schema_view.without_ui(cache_timeout=0), name="schema-json"
    ),
    path(
        "swagger/",
        schema_view.with_ui("swagger", cache_timeout=0),
        name="schema-swagger-ui",
    ),
    path("redoc/", schema_view.with_ui("redoc", cache_timeout=0), name="schema-redoc"),
    path("admin/", admin.site.urls),
    path(
        "api/v1/wallet/top-up/benefit/payment-result/",
        benefit.PaymentResultView.as_view(),
        name="wallet-top-up-benefit-payment-result",
    ),
    path("api/v1/account/", include("account.urls"), name="user-accounts"),
    path("api/v1/investor/", include("investor.urls"), name="investor"),
    path("api/v2/investor/", include("investor.urls_v2"), name="investor_v2"),
    path("api/v1/jeweler/", include("jeweler.urls"), name="jeweler"),
    path("api/v1/seller/", include("seller.urls"), name="seller"),
    path("api/v1/manufacturer/", include("manufacturer.urls"), name="manufacturer"),
    path("api/v1/admin/", include("sooq_althahab_admin.urls"), name="admin"),
    path("api/v1/webhook/shufti/", ShuftiWebhookView.as_view(), name="shufti-webhook"),
    path("api/v1/check-version/", CheckVersionView.as_view(), name="check-version"),
    path(
        "api/v1/products/<str:pk>/",
        product.ProductRetrieveAPIView.as_view(),
        name="precious-items-details",
    ),
    path(
        "api/v1/products/",
        product.ProductListAPIView.as_view(),
        name="precious-items-list",
    ),
    # Subscription APIS
    path(
        "api/v1/subscription/create-session/",
        apis.CreateSessionView.as_view(),
        name="subscription-create-session",
    ),
    path(
        "api/v1/subscription/3ds-success/",
        apis.Credimax3DSWebCallbackAPIView.as_view(),
        name="subscription-3ds-success-callback-url",
    ),
    path(
        "api/v1/card-addition/3ds-callback/",
        apis.Credimax3DSCardAdditionCallbackAPIView.as_view(),
        name="card-addition-3ds-callback-url",
    ),
    path(
        "api/v1/subscription/tokenize-card/",
        apis.TokenizeCardView.as_view(),
        name="subscription-tokenize-card",
    ),
    path(
        "api/v1/subscription/make-payment/",
        apis.CustomerInitiatedPaymentAPIView.as_view(),
        name="subscription-customer-initiated-payment",
    ),
    path(
        "api/v1/subscription/mark-failed/",
        apis.MarkTransactionAsFailedAPIView.as_view(),
        name="business-subscription-mark-failed",
    ),
    path(
        "api/v1/subscription/retry-billing/",
        RetryBillingDetailsAndMailAPIView.as_view(),
        name="subscription-retry-billing",
    ),
    path(
        "api/v1/subscription/test-subscription-fee-recurring/",
        TestSubscriptionFeeRecurringPaymentAPIView.as_view(),
        name="subscription-test-subscription-fee-recurring",
    ),
    path(
        "api/v1/subscription/test-pro-rata-recurring/",
        TestProRataRecurringPaymentAPIView.as_view(),
        name="subscription-test-pro-rata-recurring",
    ),
    path(
        "api/v1/subscription/update-business-plan/",
        UpdateBusinessSubscriptionPlanAPIView.as_view(),
        name="subscription-update-business-plan",
    ),
    path(
        "api/v1/subscription/suspend-business-plan/",
        SuspendBusinessSubscriptionPlanAPIView.as_view(),
        name="subscription-suspend-business-plan",
    ),
    path(
        "api/v1/subscription/cancel-business-plan/",
        CancelBusinessSubscriptionPlanAPIView.as_view(),
        name="subscription-cancel-business-plan",
    ),
    # Wallet APIS
    path(
        "api/v1/wallet/top-up/benefit/create-session/",
        benefit.BenefitPaymentInitView.as_view(),
        name="wallet-top-up-benefit-create-session",
    ),
    path(
        "api/v1/wallet/webhook/benefit/success/",
        benefit.BenefitSuccessView.as_view(),
        name="wallet-benefit-success-webhook",
    ),
    path(
        "api/v1/wallet/webhook/benefit/failure/",
        benefit.BenefitFailView.as_view(),
        name="wallet-benefit-failure-webhook",
    ),
    path(
        "api/v1/wallet/webhook/benefit/notification/",
        benefit.BenefitNotificationView.as_view(),
        name="wallet-benefit-notification-webhook",
    ),
    path(
        "api/v1/wallet/top-up/credimax/create-session/",
        checkout.CreatePaymentSessionAPIView.as_view(),
        name="wallet-top-up-credimax-create-session",
    ),
    path(
        "api/v1/wallet/webhook/credimax/",
        checkout.CredimaxWebhookAPIView.as_view(),
        name="wallet-credimax-webhook",
    ),
    path(
        "api/v1/wallet-balance/", wallet.WalletAPIView.as_view(), name="wallet-balance"
    ),
    path(
        "api/v1/wallet/transactions/",
        wallet.TransactionListAPIView.as_view(),
        name="wallet-transactions",
    ),
    path(
        "api/v1/wallet/transactions/<str:pk>/",
        wallet.TransactionDetailAPIView.as_view(),
        name="wallet-transaction-detail",
    ),
    path(
        "api/v1/organization/fees-and-taxes/",
        OrganizationFeesTaxesAPIView.as_view(),
        name="organization-fees-and-taxes-detail",
    ),
    path(
        "api/v1/generate-s3-presigned-url/",
        GeneratePresignedS3URLAPIView.as_view(),
        name="generate_s3_presigned_url",
    ),
    path(
        "api/v1/wallet/top-up/admin/",
        wallet.WalletTopUpViaAdminAPIView.as_view(),
        name="wallet-top-up-admin-create",
    ),
    path(
        "api/v1/wallet/withdraw/",
        wallet.WalletWithdrawAPIView.as_view(),
        name="wallet-withdraw-request-create",
    ),
    path(
        "api/v1/metals/live-price/",
        PreciousMetalPriceListAPIView.as_view(),
        name="live-metal-prices",
    ),
    # Download the receipt for a specific transaction
    path(
        "api/v1/transactions/<str:pk>/receipt/download/",
        wallet.TransactionReceiptDownloadView.as_view(),
        name="transaction-receipt-download",
    ),
    # Email the receipt for a specific transaction
    path(
        "api/v1/transactions/<str:pk>/receipt/email/",
        wallet.TransactionReceiptEmailView.as_view(),
        name="transaction-receipt-email",
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
