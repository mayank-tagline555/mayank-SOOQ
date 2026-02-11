import django_filters
from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models import Subquery
from django.db.models import Value
from django.db.models.functions import Concat
from django.db.models.functions import Trim
from django_filters import rest_framework as filters

from account.models import AdminUserRole
from account.models import BusinessAccount
from account.models import Transaction
from account.models import User
from account.models import UserAssignedBusiness
from jeweler.models import JewelryProductMarketplace
from jeweler.models import JewelryProfitDistribution
from jeweler.models import JewelryStock
from jeweler.models import JewelryStockRestockRequest
from jeweler.models import JewelryStockSale
from jeweler.models import MusharakahContractTerminationRequest
from sooq_althahab.enums.account import RiskLevel
from sooq_althahab.enums.account import SubscriptionStatusChoices
from sooq_althahab.enums.account import TransactionStatus
from sooq_althahab.enums.account import TransactionType
from sooq_althahab.enums.account import TransferVia
from sooq_althahab.enums.account import UserRoleBusinessChoices
from sooq_althahab.enums.account import UserRoleChoices
from sooq_althahab.enums.account import UserStatus
from sooq_althahab.enums.account import UserType
from sooq_althahab.enums.jeweler import ContractTerminator
from sooq_althahab.enums.jeweler import DeliveryRequestStatus
from sooq_althahab.enums.jeweler import DesignType
from sooq_althahab.enums.jeweler import RequestStatus
from sooq_althahab.enums.jeweler import StockLocation
from sooq_althahab.enums.jeweler import StockStatus
from sooq_althahab.enums.sooq_althahab_admin import MaterialType
from sooq_althahab.enums.sooq_althahab_admin import PoolStatus
from sooq_althahab_admin.models import BusinessSubscriptionPlan
from sooq_althahab_admin.models import JewelryProductColor
from sooq_althahab_admin.models import JewelryProductType
from sooq_althahab_admin.models import MaterialItem
from sooq_althahab_admin.models import MetalCaratType
from sooq_althahab_admin.models import MusharakahDurationChoices
from sooq_althahab_admin.models import Pool
from sooq_althahab_admin.models import StoneClarity
from sooq_althahab_admin.models import StoneCutShape


class InvestorBusinessFilter(django_filters.FilterSet):
    """Lightweight filter for investor business listing."""

    name = django_filters.CharFilter(
        field_name="name", lookup_expr="icontains", required=False
    )
    owner_name = django_filters.CharFilter(method="filter_owner_name", required=False)
    ordering = django_filters.OrderingFilter(
        fields=("created_at", "name"),
        label="Ordering",
    )

    class Meta:
        model = BusinessAccount
        fields = ["name", "owner_name"]

    def filter_owner_name(self, queryset, name, value):
        """Filter businesses by owner's full name."""
        return queryset.filter(
            Q(user_assigned_businesses__user__first_name__icontains=value)
            | Q(user_assigned_businesses__user__last_name__icontains=value)
        )


class BusinessFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(
        field_name="name", lookup_expr="icontains", required=False
    )
    search = django_filters.CharFilter(method="filter_search", required=False)
    business_account_type = django_filters.MultipleChoiceFilter(
        choices=UserRoleBusinessChoices.choices,
        method="filter_business_account_type",
    )
    owner_name = django_filters.CharFilter(method="filter_owner_name", required=False)
    owner_email = django_filters.CharFilter(
        field_name="user_assigned_businesses__user__email",
        lookup_expr="icontains",
        required=False,
    )
    ordering = django_filters.OrderingFilter(
        fields=("created_at", "name"),
        label="Ordering",
    )

    # Frontend-compatible business status filter. Values align with badgeTitle used in frontend:
    # DELETED, DRAFT, VERIFICATION_PENDING, NOT_SUBSCRIBED, SUSPENDED, ACTIVATED
    BUSINESS_STATUS_CHOICES = [
        ("DELETED", "DELETED"),
        ("DRAFT", "DRAFT"),
        ("VERIFICATION_PENDING", "VERIFICATION_PENDING"),
        ("NOT_SUBSCRIBED", "NOT_SUBSCRIBED"),
        ("SUSPENDED", "SUSPENDED"),
        ("ACTIVATED", "ACTIVATED"),
    ]

    user_status = django_filters.MultipleChoiceFilter(
        choices=BUSINESS_STATUS_CHOICES,
        method="filter_user_status",
        label="Business Status",
    )

    class Meta:
        model = BusinessAccount
        fields = [
            "name",
            "business_account_type",
            "owner_name",
            "owner_email",
            "user_status",
        ]

    def filter_search(self, queryset, name, value):
        """Unified search across: Business name : Owner first name, middle name, last name
        - Owner full name (first middle last)
        - Owner full name (first last)
        """

        value = value.strip()

        queryset = queryset.annotate(
            owner_full_name=Trim(
                Concat(
                    "user_assigned_businesses__user__first_name",
                    Value(" "),
                    "user_assigned_businesses__user__middle_name",
                    Value(" "),
                    "user_assigned_businesses__user__last_name",
                )
            ),
            owner_first_last_name=Trim(
                Concat(
                    "user_assigned_businesses__user__first_name",
                    Value(" "),
                    "user_assigned_businesses__user__last_name",
                )
            ),
        )

        return queryset.filter(
            Q(name__icontains=value)  # Business name
            | Q(owner_full_name__icontains=value)  # first middle last
            | Q(owner_first_last_name__icontains=value)  # first last
            | Q(user_assigned_businesses__user__first_name__icontains=value)
            | Q(user_assigned_businesses__user__middle_name__icontains=value)
            | Q(user_assigned_businesses__user__last_name__icontains=value)
        ).distinct()

    def filter_owner_name(self, queryset, name, value):
        """Filter businesses by owner's full name."""
        return queryset.filter(
            Q(user_assigned_businesses__user__first_name__icontains=value)
            | Q(user_assigned_businesses__user__last_name__icontains=value)
        )

    def filter_business_account_type(self, queryset, name, value):
        """Custom filtering for business account type."""
        return queryset.filter(business_account_type__in=value)

    def filter_user_status(self, queryset, name, value):
        """Filter businesses by computed user/business status to match frontend badge logic.

        Accepts one or more of the following values:
        DELETED, DRAFT, VERIFICATION_PENDING, NOT_SUBSCRIBED, SUSPENDED, ACTIVATED
        """
        if not value:
            return queryset

        user_assigned_business = UserAssignedBusiness.global_objects
        business_subscription_plan = BusinessSubscriptionPlan.global_objects

        # === Owner Verification Related Flags ===
        has_owner_verified = Exists(
            user_assigned_business.filter(
                business=OuterRef("pk"), is_owner=True
            ).filter(user__email_verified=True, user__phone_verified=True)
        )

        has_owner_deleted = Exists(
            user_assigned_business.filter(
                business=OuterRef("pk"), is_owner=True
            ).filter(user__account_status=UserStatus.DELETED)
        )

        has_owner_unverified_contact = Exists(
            user_assigned_business.filter(
                business=OuterRef("pk"), is_owner=True
            ).filter(Q(user__email_verified=False) | Q(user__phone_verified=False))
        )

        has_verification_pending = Exists(
            user_assigned_business.filter(
                business=OuterRef("pk"), is_owner=True
            ).filter(
                Q(user__document_verified=False)
                | Q(user__face_verified=False)
                | (
                    Q(user__business_aml_verified=False)
                    & Q(user__user_type=UserType.BUSINESS)
                )
            )
        )

        # === Latest Subscription Status Subquery ===
        latest_subscription = business_subscription_plan.filter(
            business=OuterRef("pk")
        ).order_by("-created_at")

        latest_subscription_status = Subquery(latest_subscription.values("status")[:1])

        queryset = queryset.annotate(
            _owner_verified=has_owner_verified,
            _owner_deleted=has_owner_deleted,
            _owner_unverified_contact=has_owner_unverified_contact,
            _verification_pending=has_verification_pending,
            _latest_subscription_status=latest_subscription_status,
        )

        status_q = Q()

        for st in value:
            if st == "DELETED":
                status_q |= Q(_owner_deleted=True)

            elif st == "DRAFT":
                status_q |= Q(_owner_unverified_contact=True)

            elif st == "VERIFICATION_PENDING":
                status_q |= Q(_owner_verified=True, _verification_pending=True)

            elif st == "NOT_SUBSCRIBED":
                # verified, not verification pending, and latest subscription is missing or pending/failed
                status_q |= Q(
                    _owner_verified=True,
                    _verification_pending=False,
                ) & (
                    Q(_latest_subscription_status__isnull=True)
                    | Q(
                        _latest_subscription_status__in=[
                            SubscriptionStatusChoices.PENDING,
                            SubscriptionStatusChoices.FAILED,
                        ]
                    )
                )

            elif st == "SUSPENDED":
                # verified, not verification pending, active subscription but suspended
                status_q |= Q(
                    _owner_verified=True,
                    _verification_pending=False,
                    _latest_subscription_status=SubscriptionStatusChoices.ACTIVE,
                    is_suspended=True,
                )

            elif st == "ACTIVATED":
                # verified, not verification pending, active subscription and not suspended
                status_q |= Q(
                    _owner_verified=True,
                    _verification_pending=False,
                    _latest_subscription_status=SubscriptionStatusChoices.ACTIVE,
                    is_suspended=False,
                )

        return queryset.filter(status_q).distinct()


class UserFilter(django_filters.FilterSet):
    email = filters.CharFilter(
        field_name="email", lookup_expr="icontains", required=False
    )
    fullname = filters.CharFilter(method="filter_fullname")
    role = filters.MultipleChoiceFilter(
        choices=UserRoleBusinessChoices.choices, method="filter_role"
    )
    business_name = filters.CharFilter(
        field_name="user_assigned_businesses__business__name",
        lookup_expr="icontains",
        required=False,
    )

    # Ordering filter - allows users to order results by these fields
    ordering = django_filters.OrderingFilter(
        fields=("created_at", "name"),
        label="Ordering",
    )

    class Meta:
        model = User
        fields = ["email", "fullname", "role", "business_name"]

    def filter_fullname(self, queryset, name, value):
        """Custom filtering for  field."""

        return queryset.filter(
            Q(first_name__icontains=value)
            | Q(middle_name__icontains=value)
            | Q(last_name__icontains=value)
        )

    def filter_role(self, queryset, name, value):
        """Custom filtering for role field."""
        return queryset.filter(
            user_assigned_businesses__business__business_account_type__in=value
        )


class MaterialItemFilter(django_filters.FilterSet):
    name = filters.CharFilter(
        field_name="name", lookup_expr="icontains", required=False
    )
    is_enabled = django_filters.BooleanFilter(field_name="is_enabled", required=False)

    # Ordering filter - allows users to order results by these fields
    ordering = django_filters.OrderingFilter(
        fields=(("created_at", "created_at"),),
        label="Ordering",
    )

    material_type = django_filters.ChoiceFilter(
        field_name="material_type", choices=MaterialType.choices
    )

    class Meta:
        model = MaterialItem
        fields = ["name", "is_enabled", "material_type"]


class SubAdminFilter(django_filters.FilterSet):
    role = django_filters.ChoiceFilter(
        choices=UserRoleChoices.choices, method="filter_role", label="User Role"
    )
    email = filters.CharFilter(
        field_name="email", lookup_expr="icontains", required=False
    )
    fullname = filters.CharFilter(method="filter_fullname")

    class Meta:
        model = User
        fields = ["role", "email", "fullname"]

    def filter_role(self, queryset, name, value):
        """Filter users who have been assigned the given role."""
        normalized_value = value.upper()

        role_match = AdminUserRole.objects.filter(
            user=OuterRef("pk"),
            role=normalized_value,
            is_suspended=False,  # Only include active roles
        )

        return queryset.annotate(has_role=Exists(role_match)).filter(has_role=True)

    def filter_fullname(self, queryset, name, value):
        """Filter users by first, middle, or last name."""
        return queryset.filter(
            Q(first_name__icontains=value)
            | Q(middle_name__icontains=value)
            | Q(last_name__icontains=value)
        )


class TransactionFilter(django_filters.FilterSet):
    """Filter class for Transaction model"""

    transaction_type = django_filters.MultipleChoiceFilter(
        field_name="transaction_type", choices=TransactionType.choices
    )
    status = django_filters.MultipleChoiceFilter(
        field_name="status", choices=TransactionStatus.choices
    )
    # Unified search field
    business_name = django_filters.CharFilter(method="filter_search")
    search = django_filters.CharFilter(method="filter_search")
    material_name = django_filters.CharFilter(
        field_name="purchase_request__precious_item__material_item__name",
        lookup_expr="icontains",
    )
    min_amount = django_filters.NumberFilter(field_name="amount", lookup_expr="gte")
    max_amount = django_filters.NumberFilter(field_name="amount", lookup_expr="lte")
    start_date = django_filters.DateTimeFilter(
        field_name="created_at", lookup_expr="gte"
    )
    end_date = django_filters.DateTimeFilter(
        field_name="created_at__date", lookup_expr="lte"
    )
    transfer_via = django_filters.ChoiceFilter(
        field_name="transfer_via", choices=TransferVia.choices
    )

    business_subscription_exists = django_filters.BooleanFilter(
        method="filter_business_subscription_exists",
        label="Has Business Subscription",
    )

    ordering = django_filters.OrderingFilter(
        fields=(("created_at", "created_at"),),
        label="Ordering",
    )

    class Meta:
        model = Transaction
        fields = [
            "transaction_type",
            "status",
            "business_name",
            "material_name",
            "min_amount",
            "max_amount",
            "start_date",
            "end_date",
            "transfer_via",
            "business_subscription_exists",
        ]

    def filter_search(self, queryset, name, value):
        """
        Search across:
        - Business name (from / to)
        - User full name (first middle last)
        - User full name (first last)
        - User first name, middle name, last name
        - User email
        """

        value = value.strip()

        queryset = queryset.annotate(
            created_by_full_name=Trim(
                Concat(
                    "created_by__first_name",
                    Value(" "),
                    "created_by__middle_name",
                    Value(" "),
                    "created_by__last_name",
                )
            ),
            created_by_first_last=Trim(
                Concat(
                    "created_by__first_name",
                    Value(" "),
                    "created_by__last_name",
                )
            ),
        )

        return queryset.filter(
            Q(from_business__name__icontains=value)
            | Q(to_business__name__icontains=value)
            | Q(created_by_full_name__icontains=value)
            | Q(created_by_first_last__icontains=value)
            | Q(created_by__first_name__icontains=value)
            | Q(created_by__middle_name__icontains=value)
            | Q(created_by__last_name__icontains=value)
            | Q(created_by__email__icontains=value)
        ).distinct()

    def filter_business_subscription_exists(self, queryset, name, value):
        """Filter transactions based on the existence of business_subscription."""
        if value:  # True → subscription exists
            return queryset.filter(business_subscription__isnull=False)
        else:  # False → subscription does not exist
            return queryset.filter(business_subscription__isnull=True)


class PoolFilter(filters.FilterSet):
    """Filter class for Pool model"""

    name = filters.CharFilter(lookup_expr="icontains")
    status = filters.ChoiceFilter(choices=PoolStatus.choices)
    material_type = filters.ChoiceFilter(choices=MaterialType.choices)
    material_item = filters.CharFilter(
        field_name="material_item__name", lookup_expr="icontains", required=False
    )

    # Range filters grouped with `field_name__gte/lte`
    target_min = filters.NumberFilter(field_name="target", lookup_expr="gte")
    target_max = filters.NumberFilter(field_name="target", lookup_expr="lte")

    expected_return_min = filters.NumberFilter(
        field_name="expected_return_percentage", lookup_expr="gte"
    )
    expected_return_max = filters.NumberFilter(
        field_name="expected_return_percentage", lookup_expr="lte"
    )
    risk_level = filters.MultipleChoiceFilter(
        choices=RiskLevel.choices,
        method="filter_risk_level",
    )
    created_at_min = filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_at_max = filters.DateTimeFilter(
        field_name="created_at__date", lookup_expr="lte"
    )
    ordering = django_filters.OrderingFilter(
        fields=(("created_at", "created_at"),),
        label="Ordering",
    )

    class Meta:
        model = Pool
        fields = [
            "name",
            "status",
            "material_type",
            "material_item",
            "target_min",
            "target_max",
            "expected_return_min",
            "expected_return_max",
            "created_at_min",
            "created_at_max",
            "risk_level",
        ]

    def filter_risk_level(self, queryset, name, value):
        """Custom filtering for risk level field."""

        if value:
            return queryset.filter(risk_level__in=value)
        return queryset


class CommonNameEnabledOrderingFilter(django_filters.FilterSet):
    """
    Base filter class with common filters:
    - name (icontains)
    - is_enabled (boolean)
    - ordering by created_at
    """

    name = filters.CharFilter(lookup_expr="icontains")
    is_enabled = filters.BooleanFilter(field_name="is_enabled", required=False)

    ordering = django_filters.OrderingFilter(
        fields=(("created_at", "created_at"),),
        label="Ordering",
    )

    class Meta:
        fields = ["name", "is_enabled"]


class StoneCutShapeFilter(CommonNameEnabledOrderingFilter):
    class Meta(CommonNameEnabledOrderingFilter.Meta):
        model = StoneCutShape


class MetalCaratTypeFilter(CommonNameEnabledOrderingFilter):
    class Meta(CommonNameEnabledOrderingFilter.Meta):
        model = MetalCaratType


class JewelryProductTypeFilter(CommonNameEnabledOrderingFilter):
    class Meta(CommonNameEnabledOrderingFilter.Meta):
        model = JewelryProductType


class JewelryProductColorFilter(CommonNameEnabledOrderingFilter):
    class Meta(CommonNameEnabledOrderingFilter.Meta):
        model = JewelryProductColor


class StoneClarityFilter(CommonNameEnabledOrderingFilter):
    class Meta(CommonNameEnabledOrderingFilter.Meta):
        model = StoneClarity


class MusharakahDurationChoicesFilter(django_filters.FilterSet):
    name = filters.CharFilter(lookup_expr="icontains")
    is_active = filters.BooleanFilter(field_name="is_active", required=False)
    ordering = django_filters.OrderingFilter(
        fields=(("created_at", "created_at"),),
        label="Ordering",
    )

    class Meta:
        model = MusharakahDurationChoices
        fields = ["name", "is_active"]


class MusharakahContractTerminationFilter(django_filters.FilterSet):
    business_name = django_filters.CharFilter(
        method="filter_by_business_name", label="Jeweler or Investor Business Name"
    )

    termination_request_by = django_filters.ChoiceFilter(
        choices=ContractTerminator.choices,
        field_name="termination_request_by",
        required=False,
    )
    created_at_min = filters.DateTimeFilter(
        field_name="created_at__date", lookup_expr="gte"
    )
    created_at_max = filters.DateTimeFilter(
        field_name="created_at__date", lookup_expr="lte"
    )
    status = filters.MultipleChoiceFilter(
        choices=RequestStatus.choices, method="filter_status"
    )

    class Meta:
        model = MusharakahContractTerminationRequest
        fields = [
            "business_name",
            "status",
            "termination_request_by",
            "created_at_min",
            "created_at_max",
        ]

    def filter_status(self, queryset, name, value):
        """Custom filtering for status field."""

        if value:
            return queryset.filter(status__in=value)
        return queryset

    def filter_by_business_name(self, queryset, name, value):
        return queryset.filter(
            Q(musharakah_contract_request__jeweler__name__icontains=value)
            | Q(musharakah_contract_request__investor__name__icontains=value)
        )


#######################################################################################
############################### Jewelry Buyer Filters ###############################
#######################################################################################


class JewelryStockFilter(django_filters.FilterSet):
    """Filter set for JewelryStock model."""

    product_name = django_filters.CharFilter(
        field_name="jewelry_product__product_name",
        lookup_expr="icontains",
        required=False,
    )
    location = django_filters.ChoiceFilter(
        choices=StockLocation.choices, required=False
    )
    showroom_status = django_filters.ChoiceFilter(
        choices=StockStatus.choices, required=False
    )
    marketplace_status = django_filters.ChoiceFilter(
        choices=StockStatus.choices, required=False
    )
    is_published_to_marketplace = django_filters.BooleanFilter(required=False)
    created_at_min = django_filters.DateTimeFilter(
        field_name="created_at", lookup_expr="gte", required=False
    )
    created_at_max = django_filters.DateTimeFilter(
        field_name="created_at", lookup_expr="lte", required=False
    )
    ordering = django_filters.OrderingFilter(
        fields=(
            ("created_at", "created_at"),
            ("showroom_quantity", "showroom_quantity"),
            ("marketplace_quantity", "marketplace_quantity"),
        ),
        label="Ordering",
    )

    class Meta:
        model = JewelryStock
        fields = [
            "location",
            "showroom_status",
            "marketplace_status",
            "is_published_to_marketplace",
        ]


class JewelryProductMarketplaceFilter(django_filters.FilterSet):
    """Filter set for JewelryProductMarketplace model."""

    product_name = django_filters.CharFilter(
        field_name="jewelry_product__product_name",
        lookup_expr="icontains",
        required=False,
    )
    design_type = django_filters.CharFilter(
        field_name="jewelry_product__jewelry_design__design_type",
        lookup_expr="icontains",
        required=False,
    )
    is_active = django_filters.BooleanFilter(required=False)
    published_at_min = django_filters.DateTimeFilter(
        field_name="published_at", lookup_expr="gte", required=False
    )
    published_at_max = django_filters.DateTimeFilter(
        field_name="published_at", lookup_expr="lte", required=False
    )
    ordering = django_filters.OrderingFilter(
        fields=(
            ("published_at", "published_at"),
            ("published_quantity", "published_quantity"),
        ),
        label="Ordering",
    )

    class Meta:
        model = JewelryProductMarketplace
        fields = [
            "is_active",
        ]


class JewelryStockRestockRequestFilter(django_filters.FilterSet):
    """Filter set for JewelryStockRestockRequest model."""

    product_name = django_filters.CharFilter(
        field_name="jewelry_stock__jewelry_product__product_name",
        lookup_expr="icontains",
        required=False,
    )
    status = django_filters.CharFilter(lookup_expr="iexact", required=False)
    restock_location = django_filters.ChoiceFilter(
        choices=StockLocation.choices, required=False
    )
    requested_date_min = django_filters.DateFilter(
        field_name="requested_date", lookup_expr="gte", required=False
    )
    requested_date_max = django_filters.DateFilter(
        field_name="requested_date", lookup_expr="lte", required=False
    )
    created_at_min = django_filters.DateTimeFilter(
        field_name="created_at", lookup_expr="gte", required=False
    )
    created_at_max = django_filters.DateTimeFilter(
        field_name="created_at", lookup_expr="lte", required=False
    )
    ordering = django_filters.OrderingFilter(
        fields=(
            ("created_at", "created_at"),
            ("requested_date", "requested_date"),
        ),
        label="Ordering",
    )

    class Meta:
        model = JewelryStockRestockRequest
        fields = [
            "status",
            "restock_location",
        ]


class JewelryStockSaleFilter(django_filters.FilterSet):
    """Filter set for JewelryStockSale model."""

    product_name = django_filters.CharFilter(
        field_name="jewelry_product__product_name",
        lookup_expr="icontains",
        required=False,
    )

    sale_location = django_filters.ChoiceFilter(
        choices=StockLocation.choices, required=False
    )

    customer_name = django_filters.CharFilter(lookup_expr="icontains", required=False)

    sale_date_min = django_filters.DateFilter(
        field_name="sale_date", lookup_expr="gte", required=False
    )

    sale_date_max = django_filters.DateFilter(
        field_name="sale_date", lookup_expr="lte", required=False
    )

    created_at_min = django_filters.DateTimeFilter(
        field_name="created_at", lookup_expr="gte", required=False
    )

    created_at_max = django_filters.DateTimeFilter(
        field_name="created_at", lookup_expr="lte", required=False
    )

    status = django_filters.ChoiceFilter(
        choices=DeliveryRequestStatus.choices, required=False
    )

    # ⭐ New Design Type Filter
    design_type = django_filters.ChoiceFilter(
        field_name="jewelry_product__jewelry_design__design_type",
        choices=DesignType.choices,
        required=False,
    )

    ordering = django_filters.OrderingFilter(
        fields=(
            ("sale_date", "sale_date"),
            ("created_at", "created_at"),
            ("sale_price", "sale_price"),
        ),
        label="Ordering",
    )

    class Meta:
        model = JewelryStockSale
        fields = [
            "sale_location",
            "customer_name",
            "status",
            "design_type",
        ]


class JewelryProfitDistributionFilter(django_filters.FilterSet):
    """Filter set for JewelryProfitDistribution model."""

    recipient_business_name = django_filters.CharFilter(
        method="filter_recipient_business_name",
        label="Recipient Business Name",
        required=False,
    )

    jewelry_sale_product_name = django_filters.CharFilter(
        field_name="jewelry_sale__jewelry_product__product_name",
        lookup_expr="icontains",
        required=False,
    )

    created_at_min = django_filters.DateTimeFilter(
        field_name="created_at", lookup_expr="gte", required=False
    )

    created_at_max = django_filters.DateTimeFilter(
        field_name="created_at", lookup_expr="lte", required=False
    )

    ordering = django_filters.OrderingFilter(
        fields=(("created_at", "created_at"),),
        label="Ordering",
    )

    class Meta:
        model = JewelryProfitDistribution
        fields = [
            "jewelry_sale_product_name",
            "created_at_min",
            "created_at_max",
        ]

    def filter_recipient_business_name(self, queryset, name, value):
        """Filter by recipient business name."""
        return queryset.filter(recipient_business__name__icontains=value)
