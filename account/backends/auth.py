from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

from account.models import AdminUserRole
from sooq_althahab.enums.account import UserRoleChoices


class EmailOrganizationBackend(ModelBackend):
    """
    Custom authentication backend to authenticate users using email and organization_id.
    """

    def authenticate(
        self, request, username=None, organization_id=None, role=None, **kwargs
    ):
        User = get_user_model()

        # We are treating `username` as the user's email since Django's default
        # authentication backend expects a `username` field. To maintain compatibility
        # with Django’s authentication system while allowing email-based login,
        # we reuse the `username` argument here as the email identifier.
        base_filters = {
            "email": username,
            "phone_verified": True,
            "email_verified": True,
        }

        # Add role-based filtering if a role is provided
        if role:
            base_filters[
                "user_assigned_businesses__business__business_account_type"
            ] = role

        user_query = User.objects.filter(**base_filters)

        # Case 1: If role was provided but no user found → fail immediately
        if role and not user_query.exists():
            return None

        # Case 2: If no role provided and no user found → check admin roles
        if not role and not user_query.exists():
            # Fetch all users with the given email and prefetch their roles
            user_query = User.objects.filter(email=username).prefetch_related(
                "user_roles"
            )

            # Define the list of roles that qualify a user as an admin
            admin_roles = [
                UserRoleChoices.ADMIN,
                UserRoleChoices.JEWELLERY_BUYER,
                UserRoleChoices.JEWELLERY_INSPECTOR,
                UserRoleChoices.TAQABETH_ENFORCER,
            ]

            # Check if any of the unverified users have one of the admin roles
            is_admin = AdminUserRole.objects.filter(
                user__in=user_query, role__in=admin_roles
            ).exists()

            if not is_admin:
                return None

        if organization_id:
            user_query = user_query.filter(organization_id=organization_id)
        else:
            user_query = user_query.filter(Q(is_superuser=True) | Q(is_staff=True))
        user = user_query.first()
        if user and user.check_password(kwargs.get("password")):
            return user
        return None

    def get_user(self, user_id):
        User = get_user_model()
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
