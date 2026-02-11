from django.contrib.contenttypes.models import ContentType
from django.db.models import DateTimeField
from django.db.models import ExpressionWrapper
from django.db.models import F
from django.db.models import Func
from django.db.models import Prefetch
from django.http import Http404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.generics import ListCreateAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.status import HTTP_200_OK
from rest_framework.status import HTTP_404_NOT_FOUND
from rest_framework.validators import ValidationError
from rest_framework.views import APIView

from account.models import Organization
from account.models import UserAssignedBusiness
from account.utils import get_user_or_business_name
from investor.message import MESSAGES
from investor.models import AssetContribution
from investor.serializers import PoolContributionSerializer
from investor.serializers import PoolSerializer
from investor.serializers import PoolSummarySerializer
from sooq_althahab.billing.subscription.helpers import check_subscription_feature_access
from sooq_althahab.billing.subscription.helpers import prepare_organization_details
from sooq_althahab.billing.transaction.helpers import get_organization_logo_url
from sooq_althahab.constants import POOL_CONTRIBUTION_CREATE_PERMISSION
from sooq_althahab.constants import POOL_VIEW_PERMISSION
from sooq_althahab.enums.account import SubscriptionFeatureChoices
from sooq_althahab.enums.account import UserRoleBusinessChoices
from sooq_althahab.enums.account import UserRoleChoices
from sooq_althahab.enums.account import UserType
from sooq_althahab.enums.jeweler import RequestStatus
from sooq_althahab.enums.sooq_althahab_admin import NotificationTypes
from sooq_althahab.enums.sooq_althahab_admin import PoolStatus
from sooq_althahab.helper import PermissionManager
from sooq_althahab.querysets.purchase_request import get_business_from_user_token
from sooq_althahab.tasks import generate_pdf_response
from sooq_althahab.utils import CommonPagination
from sooq_althahab.utils import generic_response
from sooq_althahab.utils import get_presigned_url_from_s3
from sooq_althahab.utils import handle_serializer_errors
from sooq_althahab.utils import send_notifications_to_organization_admins
from sooq_althahab_admin.filters import PoolFilter
from sooq_althahab_admin.message import MESSAGES as ADMIN_MESSAGES
from sooq_althahab_admin.models import Pool
from sooq_althahab_admin.models import PoolContribution
from sooq_althahab_admin.serializers import PoolDetailsSerializer
from sooq_althahab_admin.serializers import PoolResponseSerializer


class PoolListAPIView(ListAPIView):
    """Handles listing of Pools with filters."""

    permission_classes = [IsAuthenticated]
    pagination_class = CommonPagination
    serializer_class = PoolResponseSerializer
    queryset = Pool.objects.all()
    filterset_class = PoolFilter
    filter_backends = (DjangoFilterBackend,)

    def get_queryset(self):
        """Return a queryset of pools."""
        if self.request.user.is_anonymous:
            return Pool.objects.none()

        user = self.request.user
        now = timezone.now()

        # Expression to calculate the pool's closing date = created_at + pool_duration (in days)
        close_date_expr = ExpressionWrapper(
            F("created_at")
            + Func(
                F("pool_duration"), function="make_interval", days=F("pool_duration")
            ),
            output_field=DateTimeField(),
        )

        return self.queryset.annotate(close_date=close_date_expr).filter(
            organization_id=user.organization_id,
            status=PoolStatus.OPEN,
            close_date__gte=now,
        )

    @PermissionManager(POOL_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=HTTP_200_OK,
            message=ADMIN_MESSAGES["pool_fetched"],
            data=response_data,
        )


class PoolRetriveAPIView(RetrieveAPIView):
    queryset = Pool.objects.all()
    serializer_class = PoolDetailsSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.is_anonymous:
            return Pool.objects.none()

        return (
            self.queryset.select_related(
                "material_item",
                "carat_type",
                "cut_shape",
            )
            .prefetch_related(
                Prefetch(
                    "pool_contributions",
                    queryset=PoolContribution.objects.select_related(
                        "participant"
                    ).prefetch_related(
                        Prefetch(
                            "participant__asset_contributions",
                            queryset=AssetContribution.objects.select_related(
                                "purchase_request__precious_item"
                            ).prefetch_related(
                                "purchase_request__precious_item__images"
                            ),
                        )
                    ),
                )
            )
            .filter(organization_id=self.request.user.organization_id)
        )

    @PermissionManager(POOL_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except Http404:
            return generic_response(
                status_code=HTTP_404_NOT_FOUND,
                error_message=ADMIN_MESSAGES["pool_not_found"],
            )

        serializer = self.get_serializer(instance)
        return generic_response(
            data=serializer.data,
            message=ADMIN_MESSAGES["pool_fetched"],
            status_code=HTTP_200_OK,
        )


class PoolContributionListCreateAPIView(ListCreateAPIView):
    """Handles updating of Pools."""

    permission_classes = [IsAuthenticated]
    serializer_class = PoolContributionSerializer
    queryset = PoolContribution.objects.all()
    pagination_class = CommonPagination
    filterset_class = PoolFilter
    filter_backends = (DjangoFilterBackend,)

    def get_queryset(self):
        if self.request.user.is_anonymous:
            return Pool.objects.none()

        business = get_business_from_user_token(self.request, "business")
        if not business:
            return Pool.objects.none()

        queryset = Pool.objects.filter(
            organization_id=self.request.user.organization_id,
            pool_contributions__participant=business,
        ).distinct()
        return queryset

    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = PoolSerializer(page, many=True, context={"request": request})
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=HTTP_200_OK,
            message=ADMIN_MESSAGES["pool_fetched"],
            data=response_data,
        )

    @PermissionManager(POOL_CONTRIBUTION_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        """Handle POST request to create organization currency."""

        user = request.user
        organization_code = user.organization_id.code

        # If user has user type business then it get business name or else user fullname.
        name = get_user_or_business_name(request)

        # Check subscription feature access (only for INVESTOR role)
        business = get_business_from_user_token(request, "business")
        if (
            business
            and business.business_account_type == UserRoleBusinessChoices.INVESTOR
        ):
            try:
                check_subscription_feature_access(
                    business, SubscriptionFeatureChoices.JOIN_POOLS
                )
            except ValidationError as ve:
                error_msg = (
                    ve.detail[0] if isinstance(ve.detail, list) else str(ve.detail)
                )
                return generic_response(
                    status_code=status.HTTP_403_FORBIDDEN,
                    error_message=error_msg,
                )

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            try:
                pool_contribution = serializer.save()
            except ValidationError as ve:
                return generic_response(
                    error_message=str(ve.detail[0]),
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Send notification to admin
            title = "Investor has contributed their asset in Pool."
            user_type = (
                "(Business)" if user.user_type == UserType.BUSINESS else "(Individual)"
            )
            message = f"'{name}' {user_type} has contributed their asset in '{pool_contribution.pool.name}' pool."
            send_notifications_to_organization_admins(
                organization_code,
                title,
                message,
                NotificationTypes.ASSET_CONTRIBUTED_IN_POOL,
                ContentType.objects.get_for_model(Pool),
                pool_contribution.pool.id,
                UserRoleChoices.TAQABETH_ENFORCER,
            )
            return generic_response(
                status_code=status.HTTP_201_CREATED,
                message=MESSAGES["asset_contributed_in_pool"],
                data=PoolSerializer(
                    pool_contribution.pool, context={"request": request}
                ).data,
            )
        return handle_serializer_errors(serializer)


class PoolDownloadAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        """Handle GET request to download Pool details as a PDF."""

        pool = (
            Pool.objects.select_related("material_item", "carat_type")
            .filter(pk=pk)
            .first()
        )

        if not pool:
            return generic_response(
                message=ADMIN_MESSAGES["pool_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )

        organization_code = request.auth.get("organization_code")
        organization = Organization.objects.get(code=organization_code)
        organization_details = prepare_organization_details(organization)
        organization_logo_url = get_organization_logo_url(organization)

        # Get the business of the user requesting the download
        business = get_business_from_user_token(request, "business")

        # Get only the contribution from the requesting user's business
        user_contribution = None
        signature_url = None
        contributor_name = None

        if business:
            # Get the contribution for this specific business that has a signature
            user_contribution = (
                pool.pool_contributions.filter(
                    participant=business, signature__isnull=False
                )
                .exclude(signature="")
                .select_related("participant")
                .first()
            )

            if user_contribution and user_contribution.signature:
                # Convert signature URL to presigned URL for template
                presigned = get_presigned_url_from_s3(user_contribution.signature)
                signature_url = presigned.get("url") if presigned else None

                # Get the owner name from the business
                owner_assignment = (
                    UserAssignedBusiness.objects.filter(
                        business=business, is_owner=True
                    )
                    .select_related("user")
                    .first()
                )

                if owner_assignment and owner_assignment.user:
                    contributor_name = owner_assignment.user.get_full_name()
                elif business.name:
                    contributor_name = business.name

        context = {
            "terms_and_condition_en": pool.terms_and_conditions["en"],
            "terms_and_condition_ar": pool.terms_and_conditions["ar"],
            "organization_details": organization_details,
            "organization_logo_url": organization_logo_url,
            "pool": pool,
            "pool_contribution": user_contribution,
            "signature_url": signature_url,
            "contributor_name": contributor_name,
        }

        # Generate and return the PDF response directly
        return generate_pdf_response(
            "pool/pool-details.html",
            context,
            filename="pool_details.pdf",
        )


class PoolSummaryAPIView(APIView):
    permission_classes = [IsAuthenticated]
    queryset = Pool.objects.prefetch_related("pool_contributions")
    serializer = PoolSummarySerializer

    def get_queryset(self):
        if self.request.user.is_anonymous:
            return self.queryset.none()

        business = get_business_from_user_token(self.request, "business")
        if not business:
            return self.queryset.none()

        queryset = self.queryset.filter(
            organization_id=self.request.user.organization_id,
            pool_contributions__participant=business,
        )
        return queryset

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        total_open_count = queryset.filter(status=PoolStatus.OPEN).count()
        total_closed_count = queryset.filter(status=PoolStatus.CLOSED).count()
        total_settled_count = queryset.filter(status=PoolStatus.SETTLED).count()
        data = {
            "total_count": queryset.count(),
            "total_open_count": total_open_count,
            "total_closed_count": total_closed_count,
            "total_settled_count": total_settled_count,
        }

        serializer = self.serializer(data).data
        return generic_response(
            data=serializer,
            message=MESSAGES["pool_summary_retrieved"],
            status_code=status.HTTP_200_OK,
        )
