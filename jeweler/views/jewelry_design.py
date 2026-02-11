from django.db import transaction
from django.db.models import DecimalField
from django.db.models import Exists
from django.db.models import ExpressionWrapper
from django.db.models import F
from django.db.models import OuterRef
from django.db.models import Prefetch
from django.db.models import Q
from django.db.models import Sum
from django.db.models import Value
from django.db.models.functions import Coalesce
from django.http import Http404
from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.generics import ListCreateAPIView
from rest_framework.generics import RetrieveUpdateDestroyAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.validators import ValidationError
from rest_framework.views import APIView

from account.message import MESSAGES as ACCOUNT_MESSAGES
from jeweler.filters import JewelryDesignFilter
from jeweler.message import MESSAGES as JEWELER_MESSAGES
from jeweler.models import JewelryDesign
from jeweler.models import JewelryProduct
from jeweler.models import JewelryProductAttachment
from jeweler.models import JewelryProductMaterial
from jeweler.models import ManufacturingRequest
from jeweler.models import MusharakahContractDesign
from jeweler.serializers import AddDesignsToCollectionSerializer
from jeweler.serializers import JewelryDesignCollectionNameSerializer
from jeweler.serializers import JewelryDesignCreateSerializer
from jeweler.serializers import JewelryDesignResponseSerializer
from jeweler.serializers import JewelryProductResponseSerializer
from jeweler.serializers import JewelryProductUpdateSerializer
from sooq_althahab.constants import JEWELRY_DESIGN_CHANGE_PERMISSION
from sooq_althahab.constants import JEWELRY_DESIGN_CREATE_PERMISSION
from sooq_althahab.constants import JEWELRY_DESIGN_DELETE_PERMISSION
from sooq_althahab.constants import JEWELRY_DESIGN_VIEW_PERMISSION
from sooq_althahab.constants import JEWELRY_PRODUCT_CHANGE_PERMISSION
from sooq_althahab.constants import JEWELRY_PRODUCT_DELETE_PERMISSION
from sooq_althahab.constants import JEWELRY_PRODUCT_VIEW_PERMISSION
from sooq_althahab.enums.jeweler import DesignType
from sooq_althahab.helper import PermissionManager
from sooq_althahab.payment_gateway_services.credimax.subscription.free_trial_utils import (
    FreeTrialLimitationError,
)
from sooq_althahab.payment_gateway_services.credimax.subscription.free_trial_utils import (
    validate_business_action_limits,
)
from sooq_althahab.querysets.purchase_request import get_business_from_user_token
from sooq_althahab.utils import CommonPagination
from sooq_althahab.utils import generic_response
from sooq_althahab.utils import handle_serializer_errors
from sooq_althahab.utils import handle_validation_error


class JewelryDesignListCreateView(ListCreateAPIView):
    """Handles listing and creating Jewelry designs."""

    permission_classes = [IsAuthenticated]
    queryset = JewelryDesign.objects.all()
    filter_backends = (DjangoFilterBackend,)
    filterset_class = JewelryDesignFilter
    pagination_class = CommonPagination

    def get_serializer_class(self):
        return (
            JewelryDesignCreateSerializer
            if self.request.method == "POST"
            else JewelryDesignResponseSerializer
        )

    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return JewelryDesign.objects.none()

        business = get_business_from_user_token(self.request, "business")

        return (
            JewelryDesign.objects.filter(
                organization_id=user.organization_id,
                business=business,
            )
            .annotate(
                total_quantity=Coalesce(
                    Sum(
                        "jewelry_products__quantity",
                        filter=Q(jewelry_products__deleted_at__isnull=True),
                    ),
                    Value(
                        0, output_field=DecimalField(max_digits=10, decimal_places=2)
                    ),
                ),
                total_weight=Coalesce(
                    Sum(
                        ExpressionWrapper(
                            F("jewelry_products__weight")
                            * F("jewelry_products__quantity"),
                            output_field=DecimalField(max_digits=20, decimal_places=4),
                        ),
                        filter=Q(jewelry_products__deleted_at__isnull=True),
                    ),
                    Value(
                        0, output_field=DecimalField(max_digits=20, decimal_places=4)
                    ),
                ),
            )
            .prefetch_related(
                Prefetch(
                    "jewelry_products",
                    queryset=JewelryProduct.objects.filter(deleted_at__isnull=True)
                    .select_related("product_type")
                    .prefetch_related(
                        Prefetch(
                            "product_materials",
                            queryset=JewelryProductMaterial.objects.select_related(
                                "material_item",
                                "carat_type",
                                "color",
                                "shape_cut",
                                "clarity",
                            ),
                        )
                    ),
                )
            )
            .order_by("-created_at")
        )

    @PermissionManager(JEWELRY_DESIGN_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        """Handles listing Jewelry designs."""

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        return generic_response(
            data=self.get_paginated_response(serializer.data).data,
            message=JEWELER_MESSAGES["jewelry_design_fetched"],
            status_code=status.HTTP_200_OK,
        )

    @PermissionManager(JEWELRY_DESIGN_CREATE_PERMISSION)
    def post(self, request, *args, **kwargs):
        """Handles creating a Jewelry design."""

        # Check free trial limitations before creating design
        business = get_business_from_user_token(request, "business")
        if business:
            try:
                validate_business_action_limits(business, "design_creation")
            except FreeTrialLimitationError as e:
                return generic_response(
                    message=e.args[0],
                    status_code=status.HTTP_403_FORBIDDEN,
                )

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            try:
                design = serializer.save()
                return generic_response(
                    data=JewelryDesignResponseSerializer(design).data,
                    message=JEWELER_MESSAGES["jewelry_design_created"],
                    status_code=status.HTTP_201_CREATED,
                )
            except ValidationError as ve:
                # Handle ValidationError raised in create method
                return handle_validation_error(ve)

        return handle_serializer_errors(serializer)


class JewelryDesignList(ListAPIView):
    """API to fetch jewelry designs that are eligible for creating a Musharakah Contract Request."""

    permission_classes = [IsAuthenticated]
    queryset = JewelryDesign.objects.all()
    serializer_class = JewelryDesignResponseSerializer
    filter_backends = (DjangoFilterBackend,)
    filterset_class = JewelryDesignFilter
    pagination_class = CommonPagination

    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return JewelryDesign.objects.none()

        business = get_business_from_user_token(self.request, "business")

        available_products = JewelryProduct.objects.filter(
            jewelry_design_id=OuterRef("pk"),
            deleted_at__isnull=True,
            musharakah_contract_request_quantities__isnull=True,
        )

        queryset = (
            JewelryDesign.objects.filter(
                organization_id=user.organization_id,
                business=business,
            )
            .filter(Exists(available_products))
            .annotate(
                total_quantity=Coalesce(
                    Sum(
                        "jewelry_products__quantity",
                        filter=Q(jewelry_products__deleted_at__isnull=True),
                    ),
                    Value(
                        0, output_field=DecimalField(max_digits=10, decimal_places=2)
                    ),
                ),
                total_weight=Coalesce(
                    Sum(
                        ExpressionWrapper(
                            F("jewelry_products__weight")
                            * F("jewelry_products__quantity"),
                            output_field=DecimalField(max_digits=20, decimal_places=4),
                        ),
                        filter=Q(jewelry_products__deleted_at__isnull=True),
                    ),
                    Value(
                        0, output_field=DecimalField(max_digits=20, decimal_places=4)
                    ),
                ),
            )
            .prefetch_related(
                Prefetch(
                    "jewelry_products",
                    queryset=JewelryProduct.objects.filter(
                        deleted_at__isnull=True,
                        musharakah_contract_request_quantities__isnull=True,
                    )
                    .select_related("product_type")
                    .prefetch_related(
                        Prefetch(
                            "product_materials",
                            queryset=JewelryProductMaterial.objects.select_related(
                                "material_item", "carat_type", "color", "shape_cut"
                            ),
                        ),
                        "jewelry_product_attachments",
                    ),
                )
            )
            .order_by("-created_at")
            .distinct()
        )

        return queryset

    @PermissionManager(JEWELRY_DESIGN_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        """Handles listing Jewelry designs."""

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        return generic_response(
            data=self.get_paginated_response(serializer.data).data,
            message=JEWELER_MESSAGES["jewelry_design_fetched"],
            status_code=status.HTTP_200_OK,
        )


class JewelryDesignAvailableForCollectionList(ListAPIView):
    """API to fetch SINGLE jewelry designs that are available for adding to collections.

    Returns only designs that:
    - Have design_type = SINGLE
    - Are not linked to any musharakah_contract_requests
    - Are not linked to any manufacturing_requests
    """

    permission_classes = [IsAuthenticated]
    queryset = JewelryDesign.objects.all()
    serializer_class = JewelryDesignResponseSerializer
    filter_backends = (DjangoFilterBackend,)
    filterset_class = JewelryDesignFilter
    pagination_class = CommonPagination

    def get_queryset(self):
        user = self.request.user
        if user.is_anonymous:
            return JewelryDesign.objects.none()

        business = get_business_from_user_token(self.request, "business")
        queryset = (
            JewelryDesign.objects.filter(
                organization_id=user.organization_id,
                business=business,
                design_type=DesignType.SINGLE,
            )
            .filter(
                Q(musharakah_contract_designs__isnull=True)
                | Q(
                    musharakah_contract_designs__musharakah_contract_request__deleted_at__isnull=False
                )
            )
            .filter(
                Q(manufacturing_requests__isnull=True)
                | Q(manufacturing_requests__deleted_at__isnull=False)
            )
            .distinct()
            .annotate(
                total_quantity=Coalesce(
                    Sum(
                        "jewelry_products__quantity",
                        filter=Q(jewelry_products__deleted_at__isnull=True),
                    ),
                    Value(
                        0, output_field=DecimalField(max_digits=10, decimal_places=2)
                    ),
                ),
                total_weight=Coalesce(
                    Sum(
                        ExpressionWrapper(
                            F("jewelry_products__weight")
                            * F("jewelry_products__quantity"),
                            output_field=DecimalField(max_digits=20, decimal_places=4),
                        ),
                        filter=Q(jewelry_products__deleted_at__isnull=True),
                    ),
                    Value(
                        0, output_field=DecimalField(max_digits=20, decimal_places=4)
                    ),
                ),
            )
            .prefetch_related(
                Prefetch(
                    "jewelry_products",
                    queryset=JewelryProduct.objects.select_related(
                        "product_type"
                    ).prefetch_related(
                        Prefetch(
                            "product_materials",
                            queryset=JewelryProductMaterial.objects.select_related(
                                "material_item", "carat_type", "color", "shape_cut"
                            ),
                        ),
                        "jewelry_product_attachments",
                    ),
                )
            )
            .order_by("-created_at")
        )
        return queryset

    @PermissionManager(JEWELRY_DESIGN_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        """Handles listing jewelry designs available for collection addition."""

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        return generic_response(
            data=self.get_paginated_response(serializer.data).data,
            message=JEWELER_MESSAGES["jewelry_design_fetched"],
            status_code=status.HTTP_200_OK,
        )


class JewelryDesignRetrieveUpdateDeleteAPIView(RetrieveUpdateDestroyAPIView):
    """Handles retrieve and delete a Jewelry Design instance."""

    permission_classes = [IsAuthenticated]
    serializer_class = JewelryDesignResponseSerializer
    queryset = JewelryDesign.objects.all()
    http_method_names = ["patch", "get", "delete"]

    def get_queryset(self):
        return (
            JewelryDesign.objects.annotate(
                total_quantity=Coalesce(
                    Sum(
                        "jewelry_products__quantity",
                        filter=Q(jewelry_products__deleted_at__isnull=True),
                    ),
                    Value(
                        0, output_field=DecimalField(max_digits=10, decimal_places=2)
                    ),
                ),
                total_weight=Coalesce(
                    Sum(
                        ExpressionWrapper(
                            F("jewelry_products__weight")
                            * F("jewelry_products__quantity"),
                            output_field=DecimalField(max_digits=20, decimal_places=4),
                        ),
                        filter=Q(jewelry_products__deleted_at__isnull=True),
                    ),
                    Value(
                        0, output_field=DecimalField(max_digits=20, decimal_places=4)
                    ),
                ),
            )
            .prefetch_related(
                Prefetch(
                    "jewelry_products",
                    queryset=JewelryProduct.objects.filter(deleted_at__isnull=True)
                    .select_related("product_type")
                    .prefetch_related(
                        Prefetch(
                            "product_materials",
                            queryset=JewelryProductMaterial.objects.select_related(
                                "material_item",
                                "carat_type",
                                "color",
                                "shape_cut",
                                "clarity",
                            ),
                        ),
                        "jewelry_product_attachments",
                    ),
                )
            )
            .order_by("-created_at")
        )

    def get_serializer_class(self):
        return (
            JewelryDesignCreateSerializer
            if self.request.method == "PATCH"
            else JewelryDesignResponseSerializer
        )

    @PermissionManager(JEWELRY_DESIGN_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        """Handles retrieving a Jewelry Design instance."""

        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return generic_response(
                data=serializer.data,
                message=JEWELER_MESSAGES["jewelry_design_fetched"],
                status_code=status.HTTP_200_OK,
            )
        except Http404:
            return generic_response(
                error_message=JEWELER_MESSAGES["jewelry_design_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )

    @PermissionManager(JEWELRY_DESIGN_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        """Add new products to a Jewelry Design (only if type is COLLECTION)."""
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance, data=request.data, partial=True)
            if serializer.is_valid():
                try:
                    design = serializer.save()
                except ValidationError as ve:
                    return generic_response(
                        error_message=str(ve.detail[0]),
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )
                return generic_response(
                    data=JewelryDesignResponseSerializer(design).data,
                    message=JEWELER_MESSAGES["jewelry_design_updated"],
                    status_code=status.HTTP_200_OK,
                )
            return handle_serializer_errors(serializer)
        except Http404:
            return generic_response(
                error_message=JEWELER_MESSAGES["jewelry_design_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )

    @PermissionManager(JEWELRY_DESIGN_DELETE_PERMISSION)
    def delete(self, request, *args, **kwargs):
        """Deletes a Jewelry Design if not linked to manufacturing or Musharakah."""
        try:
            instance = self.get_object()
            is_design_type_single = instance.design_type == DesignType.SINGLE
            # Check for links to Manufacturing or Musharakah
            if (
                instance.musharakah_contract_designs.exists()
                or instance.manufacturing_requests.exists()
            ):
                if is_design_type_single:
                    message = JEWELER_MESSAGES["jewelry_product_delete_forbidden"]
                else:
                    message = JEWELER_MESSAGES["jewelry_design_delete_forbidden"]
                return generic_response(
                    error_message=message,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            instance.delete()

            if is_design_type_single:
                message = JEWELER_MESSAGES["jewelry_product_deleted"]
            else:
                message = JEWELER_MESSAGES["jewelry_collection_deleted"]
            return generic_response(
                message=message,
                status_code=status.HTTP_204_NO_CONTENT,
            )
        except Http404:
            return generic_response(
                error_message=JEWELER_MESSAGES["jewelry_design_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )


class JewelryProductRetrieveUpdateDeleteAPIView(RetrieveUpdateDestroyAPIView):
    """
    Update and Deletes a jewelry product only if its design is not referenced in any
    MusharakahContractRequest or ManufacturingRequest.
    """

    permission_classes = [IsAuthenticated]
    queryset = JewelryProduct.objects.select_related("jewelry_design").prefetch_related(
        "jewelry_design__manufacturing_requests",
    )
    http_method_names = ["patch", "delete", "get"]

    def get_serializer_class(self):
        return (
            JewelryProductUpdateSerializer
            if self.request.method == "PATCH"
            else JewelryProductResponseSerializer
        )

    @PermissionManager(JEWELRY_PRODUCT_VIEW_PERMISSION)
    def get(self, request, *args, **kwargs):
        """Handles retrieve a jewelry product instance."""

        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return generic_response(
                data=serializer.data,
                message=JEWELER_MESSAGES["jewelry_product_fetched"],
                status_code=status.HTTP_200_OK,
            )
        except Http404:
            return generic_response(
                error_message=JEWELER_MESSAGES["jewelry_product_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )

    @PermissionManager(JEWELRY_PRODUCT_CHANGE_PERMISSION)
    def patch(self, request, *args, **kwargs):
        """Handles update a jewelry product instance."""
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance, data=request.data, partial=True)
            if serializer.is_valid():
                product = serializer.save()

                return generic_response(
                    data=JewelryProductResponseSerializer(product).data,
                    message=JEWELER_MESSAGES["jewelry_product_updated"],
                    status_code=status.HTTP_200_OK,
                )
            return handle_serializer_errors(serializer)
        except Http404:
            return generic_response(
                error_message=JEWELER_MESSAGES["jewelry_product_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )

    @PermissionManager(JEWELRY_PRODUCT_DELETE_PERMISSION)
    def delete(self, request, *args, **kwargs):
        try:
            product = self.get_object()
            design = product.jewelry_design

            # Check if this design is used in *any* Musharakah contract or Manufacturing request
            if (
                design.musharakah_contract_designs.exists()
                or design.manufacturing_requests.exists()
            ):
                return generic_response(
                    error_message=JEWELER_MESSAGES["jewelry_product_delete_forbidden"],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            product.delete()

            if design.design_type == DesignType.SINGLE:
                design.delete()

            return generic_response(
                message=JEWELER_MESSAGES["jewelry_product_deleted"],
                status_code=status.HTTP_204_NO_CONTENT,
            )

        except Http404:
            return generic_response(
                error_message=JEWELER_MESSAGES["jewelry_product_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )


class JewelryDesignCollectionNameExistsAPIView(APIView):
    """API to check whether a report number exists in PreciousItem."""

    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(request_body=JewelryDesignCollectionNameSerializer)
    @PermissionManager(JEWELRY_DESIGN_CHANGE_PERMISSION)
    def post(self, request):
        user = request.user
        business = get_business_from_user_token(self.request, "business")
        serializer = JewelryDesignCollectionNameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        collection_name = serializer.validated_data["collection_name"]
        exists = JewelryDesign.global_objects.filter(
            name=collection_name,
            organization_id=user.organization_id,
            business=business,
        ).exists()

        message = (
            JEWELER_MESSAGES["collection_name_exists"]
            if exists
            else JEWELER_MESSAGES["collection_name_is_valid"]
        )

        return generic_response(
            data={"exists": exists},
            message=message,
        )


class AddDesignsToCollectionAPIView(APIView):
    """API to add SINGLE designs to a COLLECTION by moving their products."""

    permission_classes = [IsAuthenticated]

    @PermissionManager(JEWELRY_DESIGN_CHANGE_PERMISSION)
    def post(self, request):
        user = request.user
        business = get_business_from_user_token(request, "business")

        if not business:
            return generic_response(
                error_message=ACCOUNT_MESSAGES["business_account_not_found"],
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        serializer = AddDesignsToCollectionSerializer(data=request.data)
        if not serializer.is_valid():
            return handle_serializer_errors(serializer)

        collection_id = serializer.validated_data["collection_id"]
        single_design_ids = serializer.validated_data["single_design_ids"]

        try:
            # --------------------------------------------------
            # 1. COLLECTION validation
            # --------------------------------------------------
            collection = JewelryDesign.objects.get(
                id=collection_id,
                business=business,
                organization_id=user.organization_id,
            )

            if collection.design_type != DesignType.COLLECTION:
                return generic_response(
                    error_message=JEWELER_MESSAGES[
                        "jewelry_design_type_must_be_collection"
                    ],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Check if collection is linked to musharakah or manufacturing
            if (
                MusharakahContractDesign.objects.filter(
                    design_id=collection.id
                ).exists()
                or ManufacturingRequest.objects.filter(design_id=collection.id).exists()
            ):
                return generic_response(
                    error_message=JEWELER_MESSAGES["jewelry_product_update_forbidden"],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Get single designs
            single_designs = JewelryDesign.objects.filter(
                id__in=single_design_ids,
                business=business,
                organization_id=user.organization_id,
                design_type=DesignType.SINGLE,
            )

            if single_designs.count() != len(single_design_ids):
                return generic_response(
                    error_message=JEWELER_MESSAGES["jewelry_design_not_found"],
                    status_code=status.HTTP_404_NOT_FOUND,
                )

            # Validate that single designs are not linked to musharakah or manufacturing
            musharakah_link = MusharakahContractDesign.objects.filter(
                design_id=OuterRef("id")
            )

            manufacturing_link = ManufacturingRequest.objects.filter(
                design_id=OuterRef("id")
            )

            single_designs = single_designs.annotate(
                is_used_in_musharakah=Exists(musharakah_link),
                is_used_in_manufacturing=Exists(manufacturing_link),
            )

            for design in single_designs:
                if design.is_used_in_musharakah or design.is_used_in_manufacturing:
                    return generic_response(
                        error_message=JEWELER_MESSAGES[
                            "cannot_add_linked_designs_to_collection"
                        ],
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )

            # Move products from single designs to collection within a transaction
            with transaction.atomic():
                # Get all products from single designs
                products_to_move = JewelryProduct.objects.filter(
                    jewelry_design__in=single_designs
                ).select_related("jewelry_design")

                # Check for duplicate product names within the collection
                existing_product_names = set(
                    JewelryProduct.objects.filter(
                        jewelry_design=collection
                    ).values_list("product_name", flat=True)
                )

                for product in products_to_move:
                    if (
                        product.product_name
                        and product.product_name in existing_product_names
                    ):
                        return generic_response(
                            error_message=JEWELER_MESSAGES[
                                "jewelry_product_exists"
                            ].format(
                                product_name=product.product_name.replace(
                                    "_", " "
                                ).title()
                            ),
                            status_code=status.HTTP_400_BAD_REQUEST,
                        )
                    existing_product_names.add(product.product_name)

                # Update products to point to collection
                products_to_move.update(jewelry_design=collection)

                # Hard delete the single designs (they're now empty, permanently remove)
                for design in single_designs:
                    design.delete()

            # Return the updated collection
            updated_collection = JewelryDesign.objects.prefetch_related(
                Prefetch(
                    "jewelry_products",
                    queryset=JewelryProduct.objects.select_related(
                        "product_type"
                    ).prefetch_related(
                        Prefetch(
                            "product_materials",
                            queryset=JewelryProductMaterial.objects.select_related(
                                "material_item",
                                "carat_type",
                                "color",
                                "shape_cut",
                            ),
                        ),
                        "jewelry_product_attachments",
                    ),
                )
            ).get(id=collection_id)

            return generic_response(
                data=JewelryDesignResponseSerializer(updated_collection).data,
                message=JEWELER_MESSAGES["single_designs_added_to_collection"],
                status_code=status.HTTP_200_OK,
            )

        except JewelryDesign.DoesNotExist:
            return generic_response(
                error_message=JEWELER_MESSAGES["jewelry_design_not_found"],
                status_code=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            return generic_response(
                error_message=str(e),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
