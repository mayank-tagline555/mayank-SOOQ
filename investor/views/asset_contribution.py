from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated

from investor.message import MESSAGES
from investor.models import AssetContribution
from investor.serializers import AssetContributionSummarySerializer
from seller.filters import AssetContributionFilter
from sooq_althahab.constants import PURCHASE_REQUEST_VIEW_PERMISSION
from sooq_althahab.helper import PermissionManager
from sooq_althahab.querysets.purchase_request import get_business_from_user_token
from sooq_althahab.utils import CommonPagination
from sooq_althahab.utils import generic_response


class BaseAssetContributionView:
    """Base class for common query and accessibility logic for asset contribution."""

    def get_queryset_for_role(self, queryset):
        """Filter asset contribution based on user role and assigned business."""
        business = get_business_from_user_token(self.request, "business")
        if not business:
            return queryset.none()
        return queryset.filter(business=business)


class AssetContributionListView(BaseAssetContributionView, ListAPIView):
    """Handles listing all asset contributions (allocated assets)."""

    pagination_class = CommonPagination
    permission_classes = [IsAuthenticated]
    serializer_class = AssetContributionSummarySerializer
    filter_backends = (DjangoFilterBackend,)
    filterset_class = AssetContributionFilter

    def get_queryset(self):
        if self.request.user.is_anonymous:
            return AssetContribution.objects.none()
        queryset = AssetContribution.objects.all()
        return self.get_queryset_for_role(queryset)

    @PermissionManager(PURCHASE_REQUEST_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response_data = self.get_paginated_response(serializer.data).data
        return generic_response(
            status_code=status.HTTP_200_OK,
            message=MESSAGES["asset_contribution_fetched"],
            data=response_data,
        )
