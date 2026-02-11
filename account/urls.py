from django.urls import include
from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from account import views

router = DefaultRouter()
router.register(r"addresses", views.AddressViewSet, basename="address")
router.register(
    r"currencies",
    views.OrganizationCurrenciesViewSet,
    basename="organization-currencies",
)


urlpatterns = [
    path("token/refresh/", TokenRefreshView.as_view(), name="refresh-token"),
    path(
        "register/",
        views.RegistrationAPIView.as_view(),
        name="registration",
    ),
    path(
        "profile/",
        views.UserProfileDeleteView.as_view(),
        name="profile-delete",
    ),
    path(
        "profile/<str:pk>/",
        views.UserProfilePartialUpdateView.as_view(),
        name="profile-update",
    ),
    path(
        "login/",
        views.BackUpUserLoginAPIView.as_view(),
        name="login-user",
    ),
    path(
        "login/admin/",
        views.AdminLoginAPIView.as_view(),
        name="login-admin",
    ),
    path(
        "login/user/",
        views.UserLoginAPIView.as_view(),
        name="login-user",
    ),
    path("role/switch/", views.SwitchUserRoleAPI.as_view(), name="switch-role"),
    path("session/", views.SessionAPI.as_view(), name="session"),
    path(
        "password/change/",
        views.ChangePasswordAPIView.as_view(),
        name="change-password",
    ),
    path(
        "password/forget/otp/send/",
        views.ForgetpasswordSendOtpAPIView.as_view(),
        name="forget-password-otp-send",
    ),
    path(
        "password/forget/otp/verify/",
        views.ForgetPasswordVerifyOTPAPIView.as_view(),
        name="forget-password-otp-verify",
    ),
    path(
        "password/reset/",
        views.ResetPasswordApiView.as_view(),
        name="reset-password",
    ),
    path("bank_account/", views.BankAccountUpdateView.as_view(), name="bank_account"),
    path(
        "business/users/",
        views.BusinessUserListAPIView.as_view(),
        name="business-users-list",
    ),
    path(
        "business/update/",
        views.BusinessAccountUpdateView.as_view(),
        name="business-account-update",
    ),
    path(
        "shareholders/",
        views.ShareholderListCreateAPIView.as_view(),
        name="shareholders",
    ),
    path(
        "shareholders/<str:pk>/",
        views.ShareholderRetrieveUpdateDeleteAPIView.as_view(),
        name="shareholders",
    ),
    path("", include(router.urls)),
    path(
        "user/preference/",
        views.UserPreferenceViewSet.as_view(),
        name="user-preference-retrieve",
    ),
    path(
        "user/notifications/",
        views.NotificationListAPIView.as_view(),
        name="user-notifications-list",
    ),
    path(
        "business/cards/",
        views.BusinessSavedCardListAPIView.as_view(),
        name="user-business-saved-cards-list",
    ),
    path(
        "business/cards/session/",
        views.BusinessSavedCardSessionCreateAPIView.as_view(),
        name="user-business-saved-cards-session-create",
    ),
    path(
        "business/cards/add/",
        views.BusinessSavedCardCreateAPIView.as_view(),
        name="user-business-saved-cards-create",
    ),
    path(
        "business/cards/<str:pk>/set-default/",
        views.BusinessSavedCardSetDefaultAPIView.as_view(),
        name="user-business-saved-cards-set-default",
    ),
    path(
        "business/cards/<str:pk>/delete/",
        views.BusinessSavedCardDeleteAPIView.as_view(),
        name="user-business-saved-cards-delete",
    ),
    path(
        "user/notification/read-unread/<str:pk>/",
        views.NotificationReadUnreadStatusUpdateAPIView.as_view(),
        name="notification-read-unread-update",
    ),
    path(
        "user/notification/read-all/",
        views.AllNotificationRead.as_view(),
        name="notification-read-all-update",
    ),
    path(
        "sub-user/",
        views.SubUserCreateAPIView.as_view(),
        name="sub-user-create",
    ),
    path(
        "business/documents/",
        views.BusinessAccountDocumentCreateAPIView.as_view(),
        name="business-documents-create",
    ),
    path(
        "contact/support-requests/",
        views.ContactSupportRequestCreateAPIView.as_view(),
        name="contact-support-requests-create",
    ),
    path(
        "user/roles/",
        views.UserRolesAPIView.as_view(),
        name="user-roles",
    ),
    path("fcm-token/", views.FCMTokenUpdateAPIView.as_view(), name="fcm-token-create"),
    path(
        "subscription/usage/",
        views.SubscriptionUsageAPIView.as_view(),
        name="subscription-usage",
    ),
]
