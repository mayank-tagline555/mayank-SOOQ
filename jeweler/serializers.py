from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import DecimalField
from django.db.models import ExpressionWrapper
from django.db.models import F
from django.db.models import Q
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers
from rest_framework.serializers import CharField
from rest_framework.serializers import ListField
from rest_framework.serializers import SerializerMethodField

from account.message import MESSAGES as ACCOUNT_MESSAGES
from account.mixins import BusinessDetailsMixin
from account.models import BusinessAccount
from account.models import OrganizationCurrency
from account.models import Transaction
from account.models import Wallet
from account.utils import calculate_platform_fee
from investor.message import MESSAGES as INVESTOR_MESSAGES
from investor.models import AssetContribution
from investor.models import PreciousItemUnit
from investor.models import PreciousItemUnitMusharakahHistory
from investor.models import PurchaseRequest
from investor.utils import get_total_hold_amount_for_investor
from investor.utils import get_total_withdrawal_pending_amount
from jeweler.utils import generate_contract_details_html
from jeweler.utils import get_musharakah_contract_jewelry_product_count
from manufacturer.message import MESSAGES as MANUFACTURER_MESSAGES
from manufacturer.models import CorrectionValue
from manufacturer.models import ManufacturingEstimationRequest
from manufacturer.models import ProductManufacturingEstimatedPrice
from sooq_althahab.enums.account import PlatformFeeType
from sooq_althahab.enums.account import TransactionStatus
from sooq_althahab.enums.account import TransactionType
from sooq_althahab.enums.investor import ContributionType
from sooq_althahab.enums.jeweler import DesignType
from sooq_althahab.enums.jeweler import InspectionRejectedByChoices
from sooq_althahab.enums.jeweler import InspectionStatus
from sooq_althahab.enums.jeweler import JewelryProductAttachmentUploadedByChoices
from sooq_althahab.enums.jeweler import ManufacturingStatus
from sooq_althahab.enums.jeweler import MaterialSource
from sooq_althahab.enums.jeweler import MusharakahContractStatus
from sooq_althahab.enums.jeweler import Ownership
from sooq_althahab.enums.jeweler import RequestStatus
from sooq_althahab.enums.manufacturer import ManufactureRequestStatus
from sooq_althahab.enums.sooq_althahab_admin import MaterialType
from sooq_althahab.querysets.purchase_request import get_business_from_user_token
from sooq_althahab.utils import get_presigned_url_from_s3
from sooq_althahab_admin.message import MESSAGES as ADMIN_MESSAGES
from sooq_althahab_admin.models import MetalPriceHistory

from .message import MESSAGES as JEWELER_MESSAGES
from .models import InspectedRejectedJewelryProduct
from .models import InspectionRejectionAttachment
from .models import JewelryDesign
from .models import JewelryProduct
from .models import JewelryProductAttachment
from .models import JewelryProductInspectionAttachment
from .models import JewelryProduction
from .models import JewelryProductMaterial
from .models import JewelryProductStonePrice
from .models import JewelryProfitDistribution
from .models import JewelryStockSale
from .models import ManufacturingProductRequestedQuantity
from .models import ManufacturingRequest
from .models import ManufacturingTarget
from .models import MusharakahContractDesign
from .models import MusharakahContractRequest
from .models import MusharakahContractRequestAttachment
from .models import MusharakahContractRequestQuantity
from .models import MusharakahContractTerminationRequest
from .models import ProductionPayment
from .models import ProductionPaymentAssetAllocation


class JewelryProductMaterialCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating product material details."""

    id = serializers.CharField(required=False)

    class Meta:
        model = JewelryProductMaterial
        fields = [
            "id",
            "material_type",
            "material_item",
            "weight",
            "carat_type",
            "color",
            "quantity",
            "shape_cut",
            "clarity",
        ]


class JewelryProductCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating jewelry products with materials and attachments."""

    jewelry_product_attachments = serializers.ListField(
        child=serializers.CharField(), required=False
    )
    product_materials = JewelryProductMaterialCreateSerializer(many=True)

    class Meta:
        model = JewelryProduct
        exclude = [
            "id",
            "created_by",
            "created_at",
            "updated_by",
            "updated_at",
            "organization_id",
            "jewelry_design",
            "deleted_at",
            "restored_at",
            "transaction_id",
        ]

    def validate_weight(self, value):
        """Validate that weight is greater than zero."""
        if value is not None and value <= 0:
            raise serializers.ValidationError(ACCOUNT_MESSAGES["field_required"])
        return value

    def validate_quantity(self, value):
        """Validate that quantity is greater than zero."""
        if value is not None and value <= 0:
            raise serializers.ValidationError(ACCOUNT_MESSAGES["field_required"])
        return value

    def validate_price(self, value):
        """Validate that price is greater than zero."""
        if value is not None and value <= 0:
            raise serializers.ValidationError(ACCOUNT_MESSAGES["field_required"])
        return value


class JewelryDesignCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating and updating jewelry designs with associated products."""

    jewelry_products = JewelryProductCreateSerializer(many=True)

    class Meta:
        model = JewelryDesign
        fields = ["design_type", "name", "description", "duration", "jewelry_products"]

    def validate_name(self, value):
        """Validate that collection name is not empty or whitespace-only."""
        if value:
            # Strip whitespace from the value
            stripped_value = value.strip()
            # Check if the stripped value is empty
            if not stripped_value:
                raise serializers.ValidationError(
                    JEWELER_MESSAGES["collection_name_cannot_be_empty"]
                )
            # Return the stripped value
            return stripped_value
        # If value is None or empty, raise validation error
        raise serializers.ValidationError(
            JEWELER_MESSAGES["collection_name_cannot_be_empty"]
        )

    def validate(self, attrs):
        request = self.context["request"]
        instance = self.instance
        design_type = attrs.get("design_type") or self.instance.design_type
        name = attrs.get("name")
        jewelry_products = self.initial_data.get("jewelry_products", [])

        business = get_business_from_user_token(request, "business")
        if not business:
            raise serializers.ValidationError(
                ACCOUNT_MESSAGES["business_account_not_found"]
            )

        if instance:
            if (
                instance.musharakah_contract_designs.exists()
                or instance.manufacturing_requests.exists()
            ):
                raise serializers.ValidationError(
                    JEWELER_MESSAGES["jewelry_product_update_forbidden"]
                )

            if instance.design_type != DesignType.COLLECTION:
                raise serializers.ValidationError(
                    JEWELER_MESSAGES["cannot_add_products_to_single_design"]
                )
            if name:
                if (
                    JewelryDesign.global_objects.filter(name=name, business=business)
                    .exclude(id=instance.id)
                    .exists()
                ):
                    raise serializers.ValidationError(
                        JEWELER_MESSAGES["collection_name_exists"]
                    )
        else:
            # Validation for create
            if design_type == DesignType.SINGLE and len(jewelry_products) > 1:
                raise serializers.ValidationError(
                    JEWELER_MESSAGES["single_design_product_limit"]
                )
            if (
                design_type == DesignType.COLLECTION
                and JewelryDesign.global_objects.filter(
                    name=name, business=business
                ).exists()
            ):
                raise serializers.ValidationError(
                    JEWELER_MESSAGES["collection_name_exists"]
                )

        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        jewelry_products = validated_data.pop("jewelry_products", [])
        business = get_business_from_user_token(request, "business")

        with transaction.atomic():
            design = JewelryDesign.objects.create(
                business=business,
                created_by=request.user,
                organization_id=request.user.organization_id,
                **validated_data,
            )

            self._create_products(request, design, jewelry_products)
        return design

    def update(self, instance, validated_data):
        request = self.context.get("request")
        jewelry_products = validated_data.pop("jewelry_products", [])
        instance = super().update(instance, validated_data)

        with transaction.atomic():
            self._create_products(request, instance, jewelry_products)

        return instance

    def _create_products(self, request, design, products_data):
        business = design.business

        for product_data in products_data:
            product_name = product_data.get("product_name")
            if product_name:
                # Check if a product with the same name exists under this business
                exists = JewelryProduct.objects.filter(
                    jewelry_design__business=business,
                    product_name=product_name,
                ).exists()

                if exists:
                    raise serializers.ValidationError(
                        JEWELER_MESSAGES["jewelry_product_exists"].format(
                            product_name=product_name.replace("_", " ").title()
                        )
                    )

            product_materials = product_data.pop("product_materials", [])
            attachments = product_data.pop("jewelry_product_attachments", [])

            product = JewelryProduct.objects.create(
                created_by=request.user,
                organization_id=request.user.organization_id,
                jewelry_design=design,
                **product_data,
            )

            JewelryProductMaterial.objects.bulk_create(
                [
                    JewelryProductMaterial(jewelry_product=product, **mat)
                    for mat in product_materials
                ]
            )

            JewelryProductAttachment.objects.bulk_create(
                [
                    JewelryProductAttachment(jewelry_product=product, file=file)
                    for file in attachments
                ]
            )


class ProductAttachmentSerializer(serializers.ModelSerializer):
    """Serializer for retrieving product attachment URL and ID."""

    url = serializers.SerializerMethodField()

    class Meta:
        model = JewelryProductAttachment
        fields = ["id", "url"]

    def get_url(self, obj):
        """Generate a pre-signed URL for the given image"""

        return get_presigned_url_from_s3(obj.file)


class JewelryProductMaterialResponseSerializer(serializers.ModelSerializer):
    """Serializer for retrieving product material details."""

    material_item = serializers.CharField(source="material_item.name")
    color = serializers.CharField(source="color.name", default=None)
    carat_type = serializers.CharField(source="carat_type.name", default=None)
    shape_cut = serializers.CharField(source="shape_cut.name", default=None)
    stone_origin = serializers.CharField(
        source="material_item.stone_origin", default=None
    )

    class Meta:
        model = JewelryProductMaterial
        fields = [
            "id",
            "material_type",
            "material_item",
            "weight",
            "carat_type",
            "color",
            "quantity",
            "shape_cut",
            "clarity",
            "stone_origin",
        ]


class JewelryProductResponseSerializer(serializers.ModelSerializer):
    """Serializer for returning jewelry product details with attachments and materials."""

    jewelry_product_attachments = ProductAttachmentSerializer(many=True)
    product_materials = JewelryProductMaterialResponseSerializer(many=True)
    jewelry_design = serializers.CharField(source="jewelry_design.name")
    product_type = serializers.CharField(source="product_type.name")
    design_type = serializers.CharField(source="jewelry_design.design_type")

    class Meta:
        model = JewelryProduct
        exclude = [
            "created_by",
            "updated_by",
            "updated_at",
            "created_at",
            "organization_id",
            "deleted_at",
            "restored_at",
            "transaction_id",
        ]


class JewelryDesignResponseSerializer(serializers.ModelSerializer):
    """Serializer for returning complete jewelry design details with products."""

    jewelry_products = JewelryProductResponseSerializer(many=True)
    total_quantity = serializers.SerializerMethodField()
    total_weight = serializers.SerializerMethodField()
    can_add_designs = serializers.SerializerMethodField()

    class Meta:
        model = JewelryDesign
        fields = [
            "id",
            "design_type",
            "name",
            "description",
            "duration",
            "created_at",
            "jewelry_products",
            "total_products",
            "total_quantity",
            "total_weight",
            "can_add_designs",
        ]

    def get_total_quantity(self, obj):
        # Use annotated value if available (from queryset annotation), otherwise fallback to aggregation
        if hasattr(obj, "total_quantity"):
            return obj.total_quantity or 0
        return obj.jewelry_products.aggregate(total=Sum("quantity"))["total"] or 0

    def get_total_weight(self, obj):
        # Use annotated value if available (from queryset annotation), otherwise fallback to aggregation
        if hasattr(obj, "total_weight"):
            return obj.total_weight or 0
        products = obj.jewelry_products.annotate(
            total_weight=ExpressionWrapper(
                F("weight") * F("quantity"),
                output_field=DecimalField(max_digits=20, decimal_places=4),
            )
        )
        return products.aggregate(total=Sum("total_weight"))["total"] or 0

    def get_can_add_designs(self, obj):
        """
        Returns True if the collection can accept new designs (not linked to musharakah, manufacturing, or pools).
        Only applies to COLLECTION type designs.
        """
        if obj.design_type != "COLLECTION":
            return False

        # Check if linked to musharakah contract requests
        # Use prefetched data if available to avoid extra queries
        if (
            hasattr(obj, "_prefetched_objects_cache")
            and "musharakah_contract_requests" in obj._prefetched_objects_cache
        ):
            has_musharakah = (
                len(obj._prefetched_objects_cache["musharakah_contract_requests"]) > 0
            )
        else:
            has_musharakah = obj.musharakah_contract_designs.exists()

        # Check if linked to manufacturing requests
        if (
            hasattr(obj, "_prefetched_objects_cache")
            and "manufacturing_requests" in obj._prefetched_objects_cache
        ):
            has_manufacturing = (
                len(obj._prefetched_objects_cache["manufacturing_requests"]) > 0
            )
        else:
            has_manufacturing = obj.manufacturing_requests.exists()

        # Check if linked to pools (through musharakah contract requests)
        has_pools = False
        if has_musharakah:
            # Check if any musharakah contract requests have pools
            from sooq_althahab_admin.models import Pool

            if (
                hasattr(obj, "_prefetched_objects_cache")
                and "musharakah_contract_requests" in obj._prefetched_objects_cache
            ):
                musharakah_ids = [
                    mcr.id
                    for mcr in obj._prefetched_objects_cache[
                        "musharakah_contract_requests"
                    ]
                ]
            else:
                musharakah_ids = obj.musharakah_contract_designs.values_list(
                    "musharakah_contract_request__id", flat=True
                )
            has_pools = Pool.objects.filter(
                musharakah_contract_request_id__in=musharakah_ids
            ).exists()

        # Can add designs only if not linked to any of these
        return not (has_musharakah or has_manufacturing or has_pools)


class JewelryProductUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating jewelry product details with attachments and materials."""

    jewelry_product_attachments = ListField(
        child=serializers.CharField(), required=False
    )
    product_materials = JewelryProductMaterialCreateSerializer(many=True)
    delete_attachment_ids = ListField(
        child=CharField(), required=False, write_only=True
    )
    delete_product_material_ids = ListField(
        child=CharField(), required=False, write_only=True
    )

    class Meta:
        model = JewelryProduct
        exclude = [
            "created_by",
            "updated_by",
            "updated_at",
            "created_at",
            "organization_id",
            "deleted_at",
            "restored_at",
            "transaction_id",
        ]

    def validate_weight(self, value):
        """Validate that weight is greater than zero."""
        if value is not None and value <= 0:
            raise serializers.ValidationError(ACCOUNT_MESSAGES["field_required"])
        return value

    def validate_quantity(self, value):
        """Validate that quantity is greater than zero."""
        if value is not None and value <= 0:
            raise serializers.ValidationError(ACCOUNT_MESSAGES["field_required"])
        return value

    def validate_price(self, value):
        """Validate that price is greater than zero."""
        if value is not None and value <= 0:
            raise serializers.ValidationError(ACCOUNT_MESSAGES["field_required"])
        return value

    def validate(self, attrs):
        """Ensure the name is unique (excluding the current instance)."""
        instance = self.instance
        product_name = attrs.get("product_name")
        design = instance.jewelry_design

        if (
            design.musharakah_contract_designs.exists()
            or design.manufacturing_requests.exists()
        ):
            raise serializers.ValidationError(
                JEWELER_MESSAGES["jewelry_product_update_forbidden"],
            )

        if (
            product_name
            and JewelryProduct.objects.exclude(id=instance.id)
            .filter(product_name=product_name)
            .exists()
        ):
            raise serializers.ValidationError(
                JEWELER_MESSAGES["jewelry_product_exists"].format(
                    product_name=product_name.replace("_", " ").title()
                )
            )

        return attrs

    def update(self, instance, validated_data):
        # Pop custom write-only fields
        delete_attachment_ids = validated_data.pop("delete_attachment_ids", [])
        delete_product_material_ids = validated_data.pop(
            "delete_product_material_ids", []
        )
        jewelry_product_attachments = validated_data.pop(
            "jewelry_product_attachments", []
        )
        product_materials = validated_data.pop("product_materials", [])

        # Update core instance fields
        instance = super().update(instance, validated_data)
        instance.save()

        # Delete attachments if requested
        if delete_attachment_ids:
            JewelryProductAttachment.objects.filter(
                id__in=delete_attachment_ids
            ).delete()

        # Add new attachments
        if jewelry_product_attachments:
            JewelryProductAttachment.objects.bulk_create(
                [
                    JewelryProductAttachment(jewelry_product=instance, file=file)
                    for file in jewelry_product_attachments
                ]
            )

        # Delete materials if requested
        if delete_product_material_ids:
            JewelryProductMaterial.objects.filter(
                id__in=delete_product_material_ids
            ).delete()

        # Handle product materials (create or update)
        for material in product_materials:
            material_id = material.get("id")

            if material_id and material_id not in delete_product_material_ids:
                # Update existing material using serializer
                try:
                    obj = JewelryProductMaterial.objects.get(
                        id=material_id, jewelry_product=instance
                    )
                    for attr, value in material.items():
                        setattr(obj, attr, value)
                    obj.save()
                except JewelryProductMaterial.DoesNotExist:
                    continue  # Or raise ValidationError if desired
            else:
                # Create new material
                JewelryProductMaterial.objects.create(
                    jewelry_product=instance, **material
                )

        return instance


########################################################################################
########################## Musharakah Request Serializers ###############################
########################################################################################


class MusharakahContractRequestQuantitySerializer(serializers.ModelSerializer):
    """Serializer for jewelry product request quantity for musharakah contract request."""

    remaining_quantity = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )

    class Meta:
        model = MusharakahContractRequestQuantity
        fields = [
            "id",
            "musharakah_contract_request",
            "jewelry_product",
            "quantity",
            "remaining_quantity",
        ]
        read_only_fields = ["id", "musharakah_contract_request", "remaining_quantity"]


class MusharakahContractRequestQuantityUpdateSerializer(serializers.ModelSerializer):
    """Serializer for jewelry product request quantity for musharakah contract request."""

    class Meta:
        model = MusharakahContractRequestQuantity
        fields = ["quantity"]

    def validate(self, attrs):
        quantity = attrs.get("quantity")
        musharakah_contract_request = self.instance.musharakah_contract_request

        if not quantity:
            raise serializers.ValidationError(
                JEWELER_MESSAGES["quantity_should_not_be_zero"]
            )

        if (
            musharakah_contract_request.musharakah_contract_status
            == MusharakahContractStatus.NOT_ASSIGNED
        ):
            return attrs
        raise serializers.ValidationError(
            JEWELER_MESSAGES["musharakah_contract_active_can_not_update"]
        )


class MusharakahContractDesignCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating musharakah contract request design."""

    class Meta:
        model = MusharakahContractDesign
        fields = ["design"]


class MusharakahContractRequestCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating musharakah contract request."""

    musharakah_product_request_quantity = MusharakahContractRequestQuantitySerializer(
        many=True
    )
    musharakah_contract_request_attachments = serializers.ListField(
        child=serializers.CharField(), required=False
    )
    designs = MusharakahContractDesignCreateSerializer(many=True)
    jewelry_product_material = JewelryProductMaterialCreateSerializer(
        many=True, required=False
    )

    class Meta:
        model = MusharakahContractRequest
        fields = [
            "design_type",
            "designs",
            "target",
            "risk_level",
            "equity_min",
            "equity_max",
            "penalty_amount",
            "description",
            "musharakah_equity",
            "cash_contribution",
            "duration_in_days",
            "musharakah_contract_request_attachments",
            "musharakah_product_request_quantity",
            "jeweler_signature",
            "jewelry_product_material",
        ]
        read_only_fields = [
            "risk_level",
            "equity_min",
            "equity_max",
            "max_musharakah_weight",
            "penalty_amount",
        ]

    def validate(self, attrs):
        jewelry_product_material = attrs.get("jewelry_product_material", [])
        request = self.context["request"]
        business = get_business_from_user_token(request, "business")
        if not business:
            raise serializers.ValidationError(
                ACCOUNT_MESSAGES["business_account_not_found"]
            )

        risk_level_obj = business.risk_level
        selected_duration = attrs.get("duration_in_days")

        if selected_duration:
            if not risk_level_obj.allowed_durations.filter(
                id=selected_duration.id
            ).exists():
                raise serializers.ValidationError(
                    JEWELER_MESSAGES["musharakah_duration_validation"]
                )

        if jewelry_product_material:
            material_ids = [item["id"] for item in jewelry_product_material]

            materials = JewelryProductMaterial.objects.filter(id__in=material_ids)
            material_map = {m.id: m for m in materials}
            if len(material_map) != len(material_ids):
                raise serializers.ValidationError(
                    "One or more jewelry product materials are invalid."
                )

        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        musharakah_contract_request_attachments = validated_data.pop(
            "musharakah_contract_request_attachments", []
        )
        musharakah_product_request_quantity = validated_data.pop(
            "musharakah_product_request_quantity", []
        )
        designs = validated_data.pop("designs", [])

        jewelry_designs = JewelryDesign.objects.filter(
            id__in=[design["design"].id for design in designs]
        )

        jewelry_product_material = validated_data.pop("jewelry_product_material", [])
        # Update Jewelry Product Material (MATCH BY ID)
        if jewelry_product_material:
            material_ids = [item["id"] for item in jewelry_product_material]

            materials = JewelryProductMaterial.objects.filter(id__in=material_ids)

            material_map = {m.id: m for m in materials}

            if len(material_map) != len(material_ids):
                raise serializers.ValidationError(
                    "One or more jewelry product materials are invalid."
                )

            for material_data in jewelry_product_material:
                material = material_map[material_data["id"]]

                # Update allowed fields only
                for field, value in material_data.items():
                    if field != "id":
                        setattr(material, field, value)

                material.save(
                    update_fields=[
                        field for field in material_data.keys() if field != "id"
                    ]
                )

        # Get business from token
        business = get_business_from_user_token(request, "business")
        if not business:
            raise serializers.ValidationError(
                JEWELER_MESSAGES["business_account_not_found"]
            )

        # Check if business has a valid risk level
        if not business.risk_level:
            raise serializers.ValidationError(
                JEWELER_MESSAGES["risk_level_not_assigned"]
            )

        # Extract risk level details from assigned risk level object
        risk_level_obj = business.risk_level

        with transaction.atomic():
            musharakah_contract_request = MusharakahContractRequest.objects.create(
                jeweler=business,
                created_by=request.user,
                organization_id=request.user.organization_id,
                risk_level=risk_level_obj.risk_level,
                equity_min=risk_level_obj.equity_min,
                equity_max=risk_level_obj.equity_max,
                penalty_amount=risk_level_obj.penalty_amount,
                **validated_data,
            )

            MusharakahContractDesign.objects.bulk_create(
                [
                    MusharakahContractDesign(
                        musharakah_contract_request=musharakah_contract_request,
                        design=design,
                    )
                    for design in jewelry_designs
                ],
            )
            MusharakahContractRequestAttachment.objects.bulk_create(
                [
                    MusharakahContractRequestAttachment(
                        musharakah_contract_request=musharakah_contract_request,
                        image=image,
                    )
                    for image in musharakah_contract_request_attachments
                ]
            )

            MusharakahContractRequestQuantity.objects.bulk_create(
                [
                    MusharakahContractRequestQuantity(
                        musharakah_contract_request=musharakah_contract_request,
                        **quantity,
                    )
                    for quantity in musharakah_product_request_quantity
                ]
            )

        return musharakah_contract_request


class MusharakahContractRequestAttachmentResponseSerializer(
    serializers.ModelSerializer
):
    """Serializer for retrieving musharakah contract request attachments URL and ID."""

    url = serializers.SerializerMethodField()

    class Meta:
        model = MusharakahContractRequestAttachment
        fields = ["id", "url"]

    def get_url(self, obj):
        """Generate a pre-signed URL for the given image"""

        return get_presigned_url_from_s3(obj.image)


class MusharakahContractDesignResponseSerializer(serializers.ModelSerializer):
    """Serializer for creating musharakah contract request design."""

    design = JewelryDesignResponseSerializer()

    class Meta:
        model = MusharakahContractDesign
        fields = ["musharakah_contract_request", "design"]


class BaseMusharakahContractRequestResponseSerializer(
    BusinessDetailsMixin, serializers.ModelSerializer
):
    """Serializer for returning musharakah contract requests."""

    musharakah_contract_request_attachments = (
        MusharakahContractRequestAttachmentResponseSerializer(many=True)
    )
    musharakah_contract_request_quantities = (
        MusharakahContractRequestQuantitySerializer(many=True)
    )
    jeweler = SerializerMethodField()
    investor = SerializerMethodField()
    musharakah_contract_designs = MusharakahContractDesignResponseSerializer(many=True)
    expiry_date = serializers.CharField(read_only=True)
    investor_signature = SerializerMethodField()
    jeweler_signature = SerializerMethodField()

    class Meta:
        model = MusharakahContractRequest
        exclude = [
            "updated_by",
            "organization_id",
            "deleted_at",
            "restored_at",
            "transaction_id",
            "duration_in_days",
        ]

    def get_jeweler(self, obj):
        return self.serialize_business(obj, "jeweler")

    def get_investor(self, obj):
        return self.serialize_business(obj, "investor")

    def get_investor_signature(self, obj):
        """Generate a presigned URL for accessing the signature."""
        return get_presigned_url_from_s3(obj.investor_signature)

    def get_jeweler_signature(self, obj):
        """Generate a presigned URL for accessing the signature."""
        return get_presigned_url_from_s3(obj.jeweler_signature)


class BaseMusharakahContractTerminationRequestDetailSerializer(
    serializers.ModelSerializer
):
    termination_payment_transaction = SerializerMethodField()

    class Meta:
        model = MusharakahContractTerminationRequest
        exclude = ["updated_at"]

    def get_termination_payment_transaction(self, obj):
        from sooq_althahab_admin.serializers import (
            MusharakahContractTerminationPaymentTransactionsSerializer,
        )

        transactions = obj.musharakah_contract_request.transactions.all()
        return MusharakahContractTerminationPaymentTransactionsSerializer(
            transactions, many=True
        ).data


class MusharakahContractRequestResponseSerializer(
    BaseMusharakahContractRequestResponseSerializer
):
    """Serializer for returning musharakah contract requests with asset contribution."""

    asset_contributions = SerializerMethodField()
    precious_item_units = SerializerMethodField()
    musharakah_contract_termination_request = SerializerMethodField()

    def get_asset_contributions(self, obj):
        """
        Return asset contributions filtered to exclude invalid quantities.
        When jeweler creates contract initially, there are no asset contributions yet.
        When investor views/creates, only contributions (> 0.01) should be returned.
        """
        from investor.serializers import AssetContributionResponseSerializer

        # Filter out asset contributions with quantity <= 0 or None
        # This handles cases where contract is created but investor hasn't contributed yet,
        # or where contributions exist in the database
        contributions = obj.asset_contributions.filter(quantity__gt=Decimal("0.00"))

        if not contributions.exists():
            return []

        return AssetContributionResponseSerializer(contributions, many=True).data

    def get_precious_item_units(self, obj):
        """
        Return available precious item units for this musharakah contract.
        Only returns units with remaining_weight > 0 (not fully used).

        Includes:
        - Units directly contributed to this contract (via history)
        - Units from the same purchase requests that are available and not in other active contracts
        """
        from decimal import Decimal

        from seller.serializers import PreciousItemUnitResponseSerializer
        from sooq_althahab.enums.jeweler import MusharakahContractStatus

        # 1. Get the list of IDs that are already used in allocations for this contract
        excluded_ids = ProductionPaymentAssetAllocation.objects.filter(
            musharakah_contract=obj
        ).values_list(
            "precious_item_unit_musharakah__precious_item_unit__id", flat=True
        )

        # 2. Get purchase requests from asset contributions for this contract
        purchase_request_ids = list(
            obj.asset_contributions.values_list(
                "purchase_request_id", flat=True
            ).distinct()
        )

        if not purchase_request_ids:
            return []

        # 3. Get units from those purchase requests that are:
        #    - Not sold
        #    - Not in pools
        #    - Not in other active musharakah contracts (via FK or history)
        #    - Have remaining_weight > 0
        from investor.models import PreciousItemUnitMusharakahHistory

        # Exclude units in OTHER active musharakah contracts (not THIS contract)
        # This ensures we don't show units that are allocated to other active contracts
        active_contract_ids = (
            PreciousItemUnitMusharakahHistory.objects.filter(
                musharakah_contract__musharakah_contract_status__in=[
                    MusharakahContractStatus.ACTIVE,
                    MusharakahContractStatus.RENEW,
                    MusharakahContractStatus.UNDER_TERMINATION,
                ]
            )
            .exclude(musharakah_contract=obj)
            .values_list("precious_item_unit_id", flat=True)
            .distinct()
        )

        # Also exclude units in OTHER active contracts via FK (but include units for THIS contract)
        active_fk_unit_ids = (
            PreciousItemUnit.objects.filter(
                musharakah_contract__isnull=False,
                musharakah_contract__musharakah_contract_status__in=[
                    MusharakahContractStatus.ACTIVE,
                    MusharakahContractStatus.RENEW,
                    MusharakahContractStatus.UNDER_TERMINATION,
                ],
            )
            .exclude(musharakah_contract=obj)
            .values_list("id", flat=True)
        )

        # Combine all excluded unit IDs (exclude units in OTHER contracts, but include THIS contract's units)
        all_excluded_ids = (
            set(excluded_ids) | set(active_contract_ids) | set(active_fk_unit_ids)
        )

        # 4. Get available units from the purchase requests
        # Include units allocated to THIS contract (musharakah_contract=obj) OR not in any active contract
        # This ensures we show:
        # - Units directly allocated to this contract (via FK)
        # - Units from the same purchase requests that are available (returned from terminated contracts, etc.)
        source_units = (
            PreciousItemUnit.objects.filter(
                purchase_request_id__in=purchase_request_ids,
                sale_request__isnull=True,  # Not sold
                pool__isnull=True,  # Not in pool
            )
            .filter(
                # Include units allocated to THIS contract OR units not in any active contract
                Q(musharakah_contract=obj)
                | Q(musharakah_contract__isnull=True)
            )
            .exclude(id__in=all_excluded_ids)
            .distinct()
        )

        # 5. Filter to only include units with remaining weight > 0
        # This ensures we don't show fully used units (remaining_weight = 0)
        available_units = []
        for unit in source_units:
            remaining = unit.remaining_weight or Decimal("0.00")
            if remaining > Decimal("0.00"):
                available_units.append(unit)

        return PreciousItemUnitResponseSerializer(available_units, many=True).data

    def get_musharakah_contract_termination_request(self, obj):
        """Return the first pending termination request (single object, not list)."""

        pending_request = obj.musharakah_contract_termination_requests.filter(
            status__in=[RequestStatus.PENDING, RequestStatus.APPROVED]
        ).first()

        if not pending_request:
            return None

        return BaseMusharakahContractTerminationRequestDetailSerializer(
            pending_request
        ).data


class MusharakahContractTerminationRequestSerializer(serializers.ModelSerializer):
    """Handles serializers for Musharakah Contract Termination Request."""

    class Meta:
        model = MusharakahContractTerminationRequest
        fields = ["musharakah_contract_request"]

    def validate(self, attrs):
        musharakah_contract_request = attrs.get("musharakah_contract_request")

        if (
            musharakah_contract_request.musharakah_contract_status
            == MusharakahContractStatus.TERMINATED
        ):
            raise serializers.ValidationError(
                ADMIN_MESSAGES["musharakah_contract_request_already_terminated"]
            )

        if musharakah_contract_request.musharakah_contract_status not in [
            MusharakahContractStatus.ACTIVE,
            MusharakahContractStatus.RENEW,
        ]:
            raise serializers.ValidationError(
                ADMIN_MESSAGES["musharakah_contract_request_inactive"]
            )

        if musharakah_contract_request.status != RequestStatus.APPROVED:
            raise serializers.ValidationError(
                ADMIN_MESSAGES["musharakah_contract_request_must_be_approved"]
            )
        if MusharakahContractTerminationRequest.objects.filter(
            musharakah_contract_request=musharakah_contract_request,
            status=RequestStatus.PENDING,
        ).exists():
            raise serializers.ValidationError(
                JEWELER_MESSAGES["musharakah_contract_termination_request_exists"]
            )

        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        role = request.auth.get("role")
        musharakah_contract = validated_data.get("musharakah_contract_request")

        musharakah_contract_termination_request = (
            MusharakahContractTerminationRequest.objects.create(
                created_by=request.user,
                organization_id=request.user.organization_id,
                termination_request_by=role,
                **validated_data,
            )
        )

        musharakah_contract.musharakah_contract_status = (
            MusharakahContractStatus.UNDER_TERMINATION
        )
        musharakah_contract.save()
        return musharakah_contract_termination_request


class MusharakahContractRequestStatisticsSerializer(serializers.Serializer):
    total_count = serializers.IntegerField()
    active_count = serializers.IntegerField()
    deleted_count = serializers.IntegerField()
    terminated_count = serializers.IntegerField()
    not_assigned_count = serializers.IntegerField()
    awaiting_admin_approval_count = serializers.IntegerField()
    material_assets_value = serializers.DictField(
        child=serializers.DictField(), required=False
    )


class MusharakahContractAgreementDetailSerializer(serializers.ModelSerializer):
    """Serializer for Musharakah Contract Agreement Details."""

    musharakah_contract_request_quantities = (
        MusharakahContractRequestQuantitySerializer(many=True)
    )
    musharakah_contract_designs = MusharakahContractDesignCreateSerializer(many=True)

    class Meta:
        model = MusharakahContractRequest
        fields = [
            "design_type",
            "musharakah_contract_designs",
            "target",
            "risk_level",
            "equity_min",
            "equity_max",
            "max_musharakah_weight",
            "penalty_amount",
            "description",
            "musharakah_equity",
            "cash_contribution",
            "duration_in_days",
            "musharakah_contract_request_quantities",
            "jeweler_signature",
        ]


class MusharakahContractRequestAgreementResponseSerializer(
    BusinessDetailsMixin, serializers.ModelSerializer
):
    """Serializer for returning musharakah contract requests."""

    musharakah_contract_request_quantities = (
        MusharakahContractRequestQuantitySerializer(many=True)
    )
    jeweler = SerializerMethodField()
    musharakah_contract_designs = MusharakahContractDesignResponseSerializer(many=True)
    jeweler_signature = SerializerMethodField()

    class Meta:
        model = MusharakahContractRequest
        exclude = [
            "created_at",
            "created_by",
            "updated_at",
            "updated_by",
            "organization_id",
            "deleted_at",
            "restored_at",
            "transaction_id",
            "duration_in_days",
        ]

    def get_jeweler(self, obj):
        return self.serialize_business(obj, "jeweler")

    def get_jeweler_signature(self, obj):
        """Generate a presigned URL for accessing the signature."""
        # Handle both model instances and dictionaries
        if hasattr(obj, "jeweler_signature"):
            signature = obj.jeweler_signature
        else:
            signature = obj.get("jeweler_signature")

        if signature:
            return get_presigned_url_from_s3(signature)
        return None


########################################################################################
######################## Manufacturing Request Serializer ##############################
########################################################################################


class ManufacturerBusinessSerializer(serializers.ModelSerializer):
    """Serializer for manufacturer business account details."""

    logo = serializers.SerializerMethodField()

    class Meta:
        model = BusinessAccount
        fields = ["id", "name", "logo"]

    def get_logo(self, obj):
        """Generate a pre-signed URL for the given image"""

        return get_presigned_url_from_s3(obj.logo)


class ManufacturingTargetSerializer(serializers.ModelSerializer):
    """Serializer for manufacturing target details."""

    class Meta:
        model = ManufacturingTarget
        fields = [
            "material_type",
            "material_item",
            "weight",
            "carat_type",
            "shape_cut",
            "quantity",
            "additional_material",
            "clarity",
        ]

    def validate(self, attrs):
        shape_cut = attrs.get("shape_cut")
        quantity = attrs.get("quantity")

        if shape_cut and not quantity:
            raise serializers.ValidationError(
                JEWELER_MESSAGES["quantity_required_for_shape_cut"]
            )

        return attrs


class ManufacturingProductRequestedQuantitySerializer(serializers.ModelSerializer):
    """Serializer for manufacturing product requested quantity."""

    class Meta:
        model = ManufacturingProductRequestedQuantity
        fields = ["jewelry_product", "quantity"]


class ManufacturingRequestCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating manufacturing requests."""

    manufacturing_product_requested_quantities = (
        ManufacturingProductRequestedQuantitySerializer(many=True)
    )
    manufacturing_targets = ManufacturingTargetSerializer(many=True)
    created_by = SerializerMethodField()
    business = SerializerMethodField()

    class Meta:
        model = ManufacturingRequest
        fields = [
            "id",
            "design",
            "manufacturer_type",
            "expected_completion",
            "description",
            "direct_manufacturers",
            "manufacturing_product_requested_quantities",
            "manufacturing_targets",
            "status",
            "created_at",
            "created_by",
            "business",
        ]
        read_only_fields = ["id", "status", "created_at", "created_by", "business"]

    def validate(self, attrs):
        request = self.context["request"]
        business = get_business_from_user_token(request, "business")
        if not business:
            raise serializers.ValidationError(
                ACCOUNT_MESSAGES["business_account_not_found"]
            )

        return attrs

    def create(self, validated_data):
        request = self.context.get("request")

        manufacturing_product_requested_quantities = validated_data.pop(
            "manufacturing_product_requested_quantities", []
        )
        manufacturing_targets = validated_data.pop("manufacturing_targets", [])
        direct_manufacturers = validated_data.pop("direct_manufacturers", [])

        business = get_business_from_user_token(request, "business")

        with transaction.atomic():
            manufacturing_request = ManufacturingRequest.objects.create(
                business=business,
                created_by=request.user,
                organization_id=request.user.organization_id,
                **validated_data,
            )

            # Set ManyToMany field after creation
            if direct_manufacturers:
                manufacturing_request.direct_manufacturers.set(direct_manufacturers)

            ManufacturingTarget.objects.bulk_create(
                [
                    ManufacturingTarget(
                        manufacturing_request=manufacturing_request, **target
                    )
                    for target in manufacturing_targets
                ]
            )

            ManufacturingProductRequestedQuantity.objects.bulk_create(
                [
                    ManufacturingProductRequestedQuantity(
                        manufacturing_request=manufacturing_request, **quantity
                    )
                    for quantity in manufacturing_product_requested_quantities
                ]
            )

        return manufacturing_request

    def get_created_by(self, obj):
        data = {
            "id": obj.created_by.id,
            "name": obj.created_by.fullname,
            "profile_url": get_presigned_url_from_s3(obj.created_by.profile_image),
        }
        return data

    def get_business(self, obj):
        data = {
            "id": obj.business.id,
            "name": obj.business.name,
            "logo": get_presigned_url_from_s3(obj.business.logo),
        }
        return data


class JewelryProductAttachmentResponseSerializer(serializers.ModelSerializer):
    file = serializers.SerializerMethodField()

    class Meta:
        model = JewelryProductInspectionAttachment
        fields = ["id", "file"]
        read_only_fields = ["id"]

    def get_file(self, obj):
        """Generate a presigned URL for the image field in the model using the PresignedUrlSerializer."""
        return get_presigned_url_from_s3(obj.file)


class InspectionRejectionAttachmentSerializer(serializers.ModelSerializer):
    file = serializers.SerializerMethodField()

    class Meta:
        model = InspectionRejectionAttachment
        fields = ["id", "file"]
        read_only_fields = ["id"]

    def get_file(self, obj):
        """Generate a presigned URL for the image field in the model using the PresignedUrlSerializer."""
        return get_presigned_url_from_s3(obj.file)


class JewelryProductInspectionAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = JewelryProductInspectionAttachment
        fields = ["file"]


class InspectedRejectedJewelryProductSerializer(serializers.ModelSerializer):
    inspection_rejection_attachments = InspectionRejectionAttachmentSerializer(
        many=True
    )

    class Meta:
        model = InspectedRejectedJewelryProduct
        fields = [
            "id",
            "reason",
            "inspection_rejection_attachments",
            "created_at",
        ]
        read_only_fields = ["id"]


class ManufacturingProductRequestedQuantityResponseSerializer(
    serializers.ModelSerializer
):
    """Serializer for manufacturing product requested response quantity."""

    rejected_inspected_products = InspectedRejectedJewelryProductSerializer(many=True)
    jewelry_product = JewelryProductResponseSerializer()
    manufactured_product_attachments = SerializerMethodField()
    profit = SerializerMethodField()

    class Meta:
        model = ManufacturingProductRequestedQuantity
        fields = [
            "id",
            "jewelry_product",
            "quantity",
            "jeweler_inspection_status",
            "admin_inspection_status",
            "production_status",
            "comment",
            "rejected_inspected_products",
            "manufactured_product_attachments",
            "profit",
        ]

    def get_manufactured_product_attachments(self, obj):
        """
        Return only the latest batch of manufacturer-uploaded attachments.
        Supports multiple images uploaded in a single rework.
        """

        attachments = obj.inspection_attachments.filter(
            uploaded_by=JewelryProductAttachmentUploadedByChoices.MANUFACTURER
        ).order_by("-created_at")

        if not attachments.exists():
            return []

        # Latest uploaded image timestamp
        latest_created_at = attachments.first().created_at

        # Allow small time window to group batch uploads
        time_window_start = latest_created_at - timedelta(seconds=1)
        time_window_end = latest_created_at + timedelta(seconds=1)

        latest_batch_attachments = attachments.filter(
            created_at__range=(time_window_start, time_window_end)
        )

        return JewelryProductAttachmentResponseSerializer(
            latest_batch_attachments, many=True
        ).data

    def get_profit(self, obj):
        """Calculate profit for this design quantity from sold items."""
        # Get musharakah_contract from context (passed from parent serializer)
        musharakah_contract = self.context.get("musharakah_contract")

        if not musharakah_contract:
            return "0.00"

        # Find all sales for this manufacturing request and jewelry product
        sales = JewelryStockSale.objects.filter(
            manufacturing_request=obj.manufacturing_request,
            jewelry_product=obj.jewelry_product,
            deleted_at__isnull=True,
        )

        if not sales.exists():
            return "0.00"

        # Get profit distributions for jeweler from these sales
        profit_distributions = JewelryProfitDistribution.objects.filter(
            jewelry_sale__in=sales,
            musharakah_contract=musharakah_contract,
            recipient_type=Ownership.JEWELER,
            deleted_at__isnull=True,
        )

        # Sum up all profit amounts
        total_profit = profit_distributions.aggregate(total=Sum("profit_amount"))[
            "total"
        ] or Decimal("0.00")

        return str(total_profit.quantize(Decimal("0.01")))


class ManufacturingRequestResponseSerializer(serializers.ModelSerializer):
    """Serializer for creating manufacturing requests."""

    manufacturing_product_requested_quantities = (
        ManufacturingProductRequestedQuantityResponseSerializer(many=True)
    )
    manufacturing_targets = ManufacturingTargetSerializer(many=True)
    created_by = SerializerMethodField()
    business = SerializerMethodField()
    manufacturing_estimation = SerializerMethodField()

    class Meta:
        model = ManufacturingRequest
        fields = [
            "id",
            "design",
            "manufacturer_type",
            "expected_completion",
            "description",
            "direct_manufacturers",
            "manufacturing_product_requested_quantities",
            "manufacturing_targets",
            "status",
            "created_at",
            "created_by",
            "business",
            "manufacturing_estimation",
        ]

    def get_created_by(self, obj):
        data = {
            "id": obj.created_by.id,
            "name": obj.created_by.fullname,
            "profile_url": get_presigned_url_from_s3(obj.created_by.profile_image),
        }
        return data

    def get_business(self, obj):
        data = {
            "id": obj.business.id,
            "name": obj.business.name or obj.created_by.fullname,
            "logo": get_presigned_url_from_s3(obj.business.logo),
        }
        return data

    def get_manufacturing_estimation(self, obj):
        """Get the accepted manufacturing estimation for this request."""
        from sooq_althahab.enums.manufacturer import ManufactureRequestStatus

        estimation = (
            obj.estimation_requests.filter(status=ManufactureRequestStatus.ACCEPTED)
            .order_by("-created_at")
            .first()
        )

        if estimation:
            return ManufacturingEstimationRequestResponseSerializer(estimation).data
        return None


class ProductManufacturingEstimatedResponseSerializer(serializers.ModelSerializer):
    """Serializer for the ProductManufacturingEstimatedPrice model."""

    requested_product = ManufacturingProductRequestedQuantityResponseSerializer()

    class Meta:
        model = ProductManufacturingEstimatedPrice
        fields = [
            "id",
            "requested_product",
            "estimated_price",
            "created_at",
            "updated_at",
        ]


class ManufacturingEstimationRequestResponseSerializer(serializers.ModelSerializer):
    """Serializer for the ManufacturingEstimationRequest model."""

    estimated_prices = ProductManufacturingEstimatedResponseSerializer(many=True)
    business = serializers.SerializerMethodField()

    class Meta:
        model = ManufacturingEstimationRequest
        fields = [
            "id",
            "manufacturing_request",
            "status",
            "duration",
            "comment",
            "created_at",
            "estimated_prices",
            "business",
            "total_estimated_cost",
        ]

    def get_business(self, obj):
        return {
            "id": obj.business.id,
            "name": obj.business.name,
            "logo": get_presigned_url_from_s3(obj.business.logo),
        }


class ManufacturingRequestEstimateSerializer(serializers.ModelSerializer):
    """Serializer for the ManufacturingRequest model."""

    manufacturing_product_requested_quantities = (
        ManufacturingProductRequestedQuantityResponseSerializer(many=True)
    )
    manufacturing_targets = ManufacturingTargetSerializer(many=True)
    created_by = serializers.SerializerMethodField()
    business = serializers.SerializerMethodField()
    estimation_requests = ManufacturingEstimationRequestResponseSerializer(many=True)

    class Meta:
        model = ManufacturingRequest
        exclude = [
            "updated_by",
            "updated_at",
            "organization_id",
            "deleted_at",
            "restored_at",
            "transaction_id",
        ]

    def get_business(self, obj):
        return {
            "id": obj.business.id,
            "name": obj.business.name,
            "logo": get_presigned_url_from_s3(obj.business.logo),
        }

    def get_created_by(self, obj):
        return {
            "id": obj.created_by.id,
            "name": obj.created_by.fullname,
            "profile_url": get_presigned_url_from_s3(obj.created_by.profile_image),
        }


class ManufacturingEstimationRequestStatusUpdateSerializer(serializers.ModelSerializer):
    """Serializer to approve or reject a manufacturing estimation request."""

    status = serializers.ChoiceField(
        choices=[ManufactureRequestStatus.REJECTED, ManufactureRequestStatus.ACCEPTED],
        required=True,
    )

    class Meta:
        model = ManufacturingEstimationRequest
        fields = ["status"]

    def validate(self, attrs):
        instance = self.instance
        if instance.status != ManufactureRequestStatus.PENDING:
            raise serializers.ValidationError(
                JEWELER_MESSAGES[
                    "manufacturing_estimation_request_already_processed"
                ].format(status=instance.status.lower())
            )
        if instance.manufacturing_request.status not in [
            ManufacturingStatus.PENDING,
            ManufacturingStatus.QUOTATION_SUBMITTED,
        ]:
            raise serializers.ValidationError(
                JEWELER_MESSAGES["manufacturing_request_must_be_pending"]
            )
        return attrs

    def update(self, instance, validated_data):
        """Update manufacturing estimation request status and auto-reject others if accepted."""

        status = validated_data.get("status")
        instance.status = status

        if status == ManufactureRequestStatus.ACCEPTED:
            instance.approved_at = timezone.now()

            # If manufacturer is accepted then update status of manufacturing request with approved.
            instance.manufacturing_request.status = ManufacturingStatus.PAYMENT_PENDING
            instance.manufacturing_request.save()

            # Reject all other estimation requests for the same manufacturing_request
            ManufacturingEstimationRequest.objects.filter(
                manufacturing_request=instance.manufacturing_request,
            ).exclude(id=instance.id).update(status=ManufactureRequestStatus.REJECTED)

        instance.save()
        return instance


class ManufacturingRequestPaymentTransactionSerilaizer(serializers.ModelSerializer):
    # Accept manufacturing_estimation_request as an ID in the payload
    manufacturing_estimation_request = serializers.CharField(
        write_only=True, required=True
    )

    class Meta:
        model = Transaction
        fields = [
            "manufacturing_request",
            "manufacturing_estimation_request",
        ]

    def validate(self, attrs):
        manufacturing_request = attrs.get("manufacturing_request")

        if manufacturing_request.status in [
            ManufacturingStatus.APPROVED,
            ManufacturingStatus.COMPLETED,
        ]:
            raise serializers.ValidationError(
                {
                    "manufacturing_request": JEWELER_MESSAGES[
                        "manufacturing_request_paymet_already_completed"
                    ]
                }
            )

        manufacturing_estimation_request_id = attrs.get(
            "manufacturing_estimation_request"
        )

        manufacturing_estimation_request = (
            ManufacturingEstimationRequest.objects.select_related(
                "business", "manufacturing_request"
            )
            .filter(id=manufacturing_estimation_request_id)
            .first()
        )

        if not manufacturing_estimation_request:
            raise serializers.ValidationError(
                JEWELER_MESSAGES["manufacturing_estimation_request_not_found"]
            )

        # Validate that the estimation request belongs to the manufacturing request
        if (
            manufacturing_estimation_request.manufacturing_request
            != manufacturing_request
        ):
            raise serializers.ValidationError(
                JEWELER_MESSAGES["manufacturing_estimation_request_mismatch"]
            )

        # Validate that the estimation request has ACCEPTED status
        if manufacturing_estimation_request.status != ManufactureRequestStatus.ACCEPTED:
            raise serializers.ValidationError(
                JEWELER_MESSAGES["manufacturing_estimation_request_not_accepted"]
            )

        # Replace ID with actual object in attrs
        attrs.update(
            {
                "manufacturing_estimation_request": manufacturing_estimation_request,
            }
        )
        return attrs

    def create(self, validated_data):
        with transaction.atomic():
            # Get the user making the request
            user = self.context.get("request").user

            # Get manufacturing request and estimation request ID
            manufacturing_request = validated_data.get("manufacturing_request")
            manufacturing_estimation_request = validated_data.get(
                "manufacturing_estimation_request"
            )

            # VAT rate from the user's organization
            organization_vat_rate = user.organization_id.vat_rate

            # Get total cost estimated by manufacturer
            total_estimated_cost = manufacturing_estimation_request.total_estimated_cost

            # Calculate platform fee first (based on manufacturing fee)
            platform_fee = calculate_platform_fee(
                total_estimated_cost, user.organization_id
            )

            # Calculate VAT on (manufacturing fee + platform fee) - Bahrain VAT standard practice
            # VAT is applied to the total taxable amount including service fees
            vat = (total_estimated_cost + platform_fee) * organization_vat_rate

            # Determine source (jeweler) and target (manufacturer) businesses
            from_business = manufacturing_request.business
            to_business = manufacturing_estimation_request.business

            # Calculate total transaction amount
            total_amount = total_estimated_cost + platform_fee + vat

            # Get wallets for both jeweler and manufacturer
            jeweler_business_wallet = manufacturing_request.business.wallets.first()
            manufacturer_business_wallet = (
                manufacturing_estimation_request.business.wallets.first()
            )

            # Calculate amounts already hold or pending for withdrawal
            total_hold_amount_for_purchase_request = get_total_hold_amount_for_investor(
                from_business
            )

            total_withdrawal_pending_amount = get_total_withdrawal_pending_amount(
                from_business
            )

            # Check for sufficient balance
            available_balance = (
                jeweler_business_wallet.balance
                - total_hold_amount_for_purchase_request
                - total_withdrawal_pending_amount
            )

            # Ensure jeweler has sufficient funds
            if available_balance < total_amount:
                raise serializers.ValidationError(
                    INVESTOR_MESSAGES["insufficient_balance"]
                )

            # Update balances for both jeweler and manufacturer
            jeweler_business_wallet.balance -= total_amount
            jeweler_business_wallet.save()

            manufacturer_business_wallet.balance += total_estimated_cost
            manufacturer_business_wallet.save()

            # Determine platform fee rate (only if type is percentage)
            platform_fee_rate = (
                user.organization_id.platform_fee_rate
                if user.organization_id.platform_fee_type == PlatformFeeType.PERCENTAGE
                else None
            )

            # Create the transaction record
            manufacturing_request_payment_transaction = Transaction.objects.create(
                from_business=from_business,
                to_business=to_business,
                manufacturing_request=manufacturing_request,
                platform_fee_rate=platform_fee_rate,
                platform_fee=platform_fee,
                vat_rate=organization_vat_rate,
                vat=vat,
                amount=total_amount,
                transaction_type=TransactionType.PAYMENT,
                status=TransactionStatus.SUCCESS,
                created_by=user,
            )
            manufacturing_request_payment_transaction.save()

            # Mark the manufacturing request as approved
            manufacturing_request.status = ManufacturingStatus.COMPLETED
            manufacturing_request.save()

            # Create a production record for the approved request
            delivery_date = manufacturing_request.created_at + timedelta(
                days=manufacturing_request.expected_completion
            )

            JewelryProduction.objects.create(
                manufacturing_request=manufacturing_request,
                design=manufacturing_request.design,
                manufacturer=manufacturing_estimation_request.business,
                delivery_date=delivery_date,
                created_by=user,
                organization_id=user.organization_id,
            )

        return manufacturing_request_payment_transaction


class JewelryProductionProductJewelerInspectionStatusSerializer(
    serializers.ModelSerializer
):
    reason = serializers.CharField(required=False)

    class Meta:
        model = ManufacturingProductRequestedQuantity
        fields = ["id", "jeweler_inspection_status", "reason"]
        read_only_fields = ["id"]
        extra_kwargs = {"reason": {"write_only": True}}

    def validate(self, attrs):
        if self.instance.jeweler_inspection_status != RequestStatus.PENDING:
            raise serializers.ValidationError(
                ADMIN_MESSAGES["jewelry_product_inspection_status_must_be_pending"]
            )
        return attrs

    def update(self, instance, validated_data):
        reason = validated_data.pop("reason", None)
        jeweler_inspection_status = validated_data.get("jeweler_inspection_status")

        instance = super().update(instance, validated_data)

        if jeweler_inspection_status == RequestStatus.REJECTED and reason:
            InspectedRejectedJewelryProduct.objects.create(
                manufacturing_product=instance,
                rejected_by=InspectionRejectedByChoices.JEWELLERY_INSPECTOR,
                reason=reason,
            )
        return instance


class AllJewelryProductStatusUpdateSerializers(serializers.Serializer):
    jeweler_inspection_status = serializers.ChoiceField(
        choices=RequestStatus.choices, required=True
    )

    def validate(self, attrs):
        instance = self.instance
        if not instance:
            raise serializers.ValidationError(
                MANUFACTURER_MESSAGES["jewelry_production_not_found"]
            )

        if instance.is_jeweler_approved:
            raise serializers.ValidationError(
                MANUFACTURER_MESSAGES["jeweler_status_already_updated"]
            )

        attrs["manufacturing_request"] = instance.manufacturing_request
        return attrs

    def update(self, instance, validated_data):
        manufacturing_request = validated_data.get("manufacturing_request")
        jeweler_inspection_status = validated_data.get("jeweler_inspection_status")
        ManufacturingProductRequestedQuantity.objects.filter(
            manufacturing_request=manufacturing_request
        ).update(jeweler_inspection_status=jeweler_inspection_status)
        if jeweler_inspection_status == RequestStatus.APPROVED:
            instance.is_jeweler_approved = True
            instance.save()
        return instance


class ProductionPaymentAssetContributionSerializer(serializers.ModelSerializer):
    """
    Serializer for asset contributions in production payment.
    Now supports passing precious_item_unit (IDs) directly with each asset.
    """

    precious_item_unit = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="List of precious item unit IDs (e.g., 'pui_...') for this asset. "
        "Length should match quantity.",
    )

    class Meta:
        model = AssetContribution
        fields = ["purchase_request", "quantity", "precious_item_unit"]


class ProductionPaymentAssetAllocationSerializer(serializers.ModelSerializer):
    """
    Serializer for ProductionPaymentAssetAllocation model.

    PR CHANGES - NEW SERIALIZER:
    - Added support for tracking serial-numbered precious item units in production payments
    - Enables traceability of which exact units were used in fulfilling a production payment
    - Supports both direct asset contributions and Musharakah-based payments
    - Links specific PreciousItemUnits to ProductionPayment records with weight tracking
    """

    precious_item_unit = serializers.CharField()

    class Meta:
        model = ProductionPaymentAssetAllocation
        fields = ["precious_item_unit", "weight"]


class ProductionPaymentSerializer(serializers.ModelSerializer):
    """
    Serializer for creating and validating Production Payment records
    after jewelry production completion and admin inspection.
    Handles multiple payment types: CASH, ASSET, MUSHARAKAH, and combinations.
    """

    assets = ProductionPaymentAssetContributionSerializer(many=True, required=False)
    # Added support for tracking serial-numbers precious item units in payments
    asset_allocation_for_production_payment = (
        ProductionPaymentAssetAllocationSerializer(many=True, required=False)
    )

    class Meta:
        model = ProductionPayment
        fields = [
            "jewelry_production",
            "musharakah_contract",
            "payment_type",
            "assets",
            "asset_allocation_for_production_payment",
        ]

    def validate(self, attrs):
        """
        Validate payment-specific requirements.
        If payment type is ASSET, ensure the contributed assets
        match the material requirements for the production.
        """
        payment_type = attrs.get("payment_type")
        jewelry_production = attrs.get("jewelry_production")
        musharakah_contract = attrs.get("musharakah_contract")
        asset_allocation_for_production_payment = attrs.get(
            "asset_allocation_for_production_payment", []
        )
        is_payment_type_asset = payment_type == MaterialSource.ASSET
        is_payment_type_musharakah = payment_type == MaterialSource.MUSHARAKAH
        is_payment_type_musharakah_and_asset = (
            payment_type == MaterialSource.MUSHARAKAH_AND_ASSET
        )

        # Enhanced validation for precious item unit tracking
        # Extract precious item unit IDs from assets if provided, otherwise use asset_allocation_for_production_payment
        unit_ids_from_assets = []
        if is_payment_type_asset:
            assets = attrs.get("assets", [])
            for asset in assets:
                precious_item_units = asset.get("precious_item_unit", [])
                if precious_item_units:
                    unit_ids_from_assets.extend(precious_item_units)

        # Use precious item unit IDs from assets if provided, otherwise fall back to asset_allocation_for_production_payment
        if unit_ids_from_assets:
            # Fetch PreciousItemUnit objects to get their weight
            from investor.models import PreciousItemUnit
            from sooq_althahab.enums.sooq_althahab_admin import MaterialType

            # Fetch units by their IDs
            precious_item_units_queryset = PreciousItemUnit.objects.filter(
                id__in=unit_ids_from_assets
            ).select_related(
                "purchase_request__precious_item__precious_metal",
                "purchase_request__precious_item__precious_stone",
            )

            # Validate that all provided unit IDs were found
            found_unit_ids = {str(unit.id) for unit in precious_item_units_queryset}
            missing_unit_ids = [
                unit_id
                for unit_id in unit_ids_from_assets
                if str(unit_id) not in found_unit_ids
            ]

            if missing_unit_ids:
                raise serializers.ValidationError(
                    JEWELER_MESSAGES["invalid_precious_item_unit"].format(
                        units=", ".join(missing_unit_ids)
                    )
                )

            # Create a mapping of purchase_request_id -> set of unit IDs for efficient lookup
            units_by_purchase_request = {}
            for unit in precious_item_units_queryset:
                purchase_request_id = str(unit.purchase_request.id)
                if purchase_request_id not in units_by_purchase_request:
                    units_by_purchase_request[purchase_request_id] = set()
                units_by_purchase_request[purchase_request_id].add(str(unit.id))

            # Validate each asset's precious item unit IDs belong to its purchase request
            for asset_index, asset in enumerate(assets):
                purchase_request = asset.get("purchase_request")
                # Normalize purchase request ID to string
                if isinstance(purchase_request, str):
                    purchase_request_id = purchase_request
                elif hasattr(purchase_request, "id"):
                    purchase_request_id = str(purchase_request.id)
                else:
                    purchase_request_id = str(purchase_request)

                asset_precious_item_unit_ids = asset.get("precious_item_unit", [])
                if asset_precious_item_unit_ids:
                    # Get valid unit IDs for this purchase request
                    valid_unit_ids_for_pr = units_by_purchase_request.get(
                        purchase_request_id, set()
                    )

                    # Find unit IDs that don't belong to this purchase request
                    invalid_unit_ids = [
                        str(unit_id)
                        for unit_id in asset_precious_item_unit_ids
                        if str(unit_id) not in valid_unit_ids_for_pr
                    ]

                    if invalid_unit_ids:
                        raise serializers.ValidationError(
                            JEWELER_MESSAGES[
                                "precious_item_unit_purchase_request_mismatch"
                            ].format(
                                units=", ".join(invalid_unit_ids),
                                purchase_request_id=purchase_request_id,
                            )
                        )

            # Build asset_allocation_for_production_payment with weight
            asset_allocation_list = []
            for unit in precious_item_units_queryset:
                # Calculate weight based on material type
                weight = Decimal("0.00")
                if unit.purchase_request and unit.purchase_request.precious_item:
                    precious_item = unit.purchase_request.precious_item
                    if precious_item.material_type == MaterialType.METAL:
                        # For metals, use remaining_weight or full weight
                        weight = unit.remaining_weight or (
                            precious_item.precious_metal.weight
                            if precious_item.precious_metal
                            else Decimal("0.00")
                        )
                    elif precious_item.material_type == MaterialType.STONE:
                        # For stones, use the stone weight
                        weight = (
                            precious_item.precious_stone.weight
                            if precious_item.precious_stone
                            else Decimal("0.00")
                        )

                asset_allocation_list.append(
                    {"precious_item_unit": str(unit.id), "weight": weight}
                )

            attrs["asset_allocation_for_production_payment"] = asset_allocation_list
            asset_allocation_for_production_payment = attrs[
                "asset_allocation_for_production_payment"
            ]
        else:
            asset_allocation_for_production_payment = attrs.get(
                "asset_allocation_for_production_payment", []
            )

        if (
            is_payment_type_asset
            or is_payment_type_musharakah
            or is_payment_type_musharakah_and_asset
        ):
            if not asset_allocation_for_production_payment:
                raise serializers.ValidationError(
                    JEWELER_MESSAGES[
                        "production_payment_asset_allocation_required"
                    ].format(payment_type=payment_type.lower())
                )

        # Ensure the jewelry production payment is already completed.
        if jewelry_production.is_payment_completed:
            raise serializers.ValidationError(
                JEWELER_MESSAGES["jewelry_production_payment_already_completed"]
            )

        # Ensure the jewelry production has been approved by the admin inspection.
        if jewelry_production.admin_inspection_status not in [
            InspectionStatus.COMPLETED,
            InspectionStatus.ADMIN_APPROVAL,
        ]:
            raise serializers.ValidationError(
                JEWELER_MESSAGES["jewelry_production_inspection_must_by_admin_approved"]
            )

        # Validate asset contributions if payment is being made using assets
        if is_payment_type_asset:
            assets = attrs.get("assets", [])

            if not assets:
                raise serializers.ValidationError(
                    JEWELER_MESSAGES["assets_required_for_asset_payment"]
                )

            # Validate that each asset has precious item unit IDs matching its quantity
            for idx, asset in enumerate(assets):
                quantity = Decimal(str(asset.get("quantity", 0)))
                precious_item_units = asset.get("precious_item_unit", [])

                if quantity <= 0:
                    raise serializers.ValidationError(
                        JEWELER_MESSAGES[
                            "asset_quantity_must_be_greater_than_zero"
                        ].format(index=idx)
                    )

                # If precious_item_unit is provided in the asset, validate it matches quantity
                if precious_item_units:
                    if len(precious_item_units) != int(quantity):
                        raise serializers.ValidationError(
                            JEWELER_MESSAGES[
                                "asset_serial_numbers_quantity_mismatch"
                            ].format(
                                index=idx,
                                serial_count=len(precious_item_units),
                                quantity=int(quantity),
                            )
                        )

            # Total quantity contributed via asset purchase requests
            total_requested_quantity = sum(
                Decimal(str(asset.get("quantity", 0))) for asset in assets
            )

            # Total number of serial-numbered units provided
            total_serial_units = Decimal(len(asset_allocation_for_production_payment))

            # Validate: the number of provided serials must match the requested quantity
            if total_serial_units != total_requested_quantity:
                raise serializers.ValidationError(
                    JEWELER_MESSAGES["total_serial_numbers_quantity_mismatch"].format(
                        serial_count=int(total_serial_units),
                        quantity=int(total_requested_quantity),
                    )
                )

            self._validate_asset_requirements(
                assets,
                attrs.get("jewelry_production"),
            )

            # Validation: Ensure Musharakah contributions meet manufacturing requirements
            if is_payment_type_musharakah or is_payment_type_musharakah_and_asset:
                # --------------------------------------------------------
                # Step 1: Build a map of contributed products from Musharakah contract
                # --------------------------------------------------------
                contributed_product_map = {}
                contributed_products = MusharakahContractRequestQuantity.objects.filter(
                    musharakah_contract_request=musharakah_contract
                )
                for product in contributed_products:
                    # Map structure: { jewelry_product: contributed_quantity }
                    contributed_product_map[product.jewelry_product] = product.quantity

                # --------------------------------------------------------
                # Step 2: Build a map of required products from manufacturing request
                # --------------------------------------------------------
                required_products_map = {}
                required_products = (
                    ManufacturingProductRequestedQuantity.objects.filter(
                        manufacturing_request=jewelry_production.manufacturing_request
                    )
                )
                for product in required_products:
                    # Map structure: { jewelry_product: required_quantity }
                    required_products_map[product.jewelry_product] = product.quantity

                # --------------------------------------------------------
                # Step 3: Compare contributed with required quantities
                # --------------------------------------------------------
                for key, required in required_products_map.items():
                    # Get contributed quantity for the current product, defaulting to 0 if not contributed
                    contributed = contributed_product_map.get(key, Decimal(0)).quantize(
                        Decimal("0.00")
                    )

                    # Normalize required quantity with decimal precision
                    required = Decimal(required or 0).quantize(Decimal("0.00"))

                    # --------------------------------------------------------
                    # Step 4: Raise error if contribution is insufficient
                    # --------------------------------------------------------
                    if contributed < required:
                        raise serializers.ValidationError(
                            JEWELER_MESSAGES["insufficient_contribution_for_material"]
                        )
        return super().validate(attrs)

    def create(self, validated_data):
        """
        Handles creation of a production payment record:
        - Computes amounts/musharakah/asset based on payment type
        - Creates associated asset contributions
        - Updates wallet balances
        - Creates the transaction record
        """

        with transaction.atomic():
            request = self.context["request"]
            business = get_business_from_user_token(request, "business")
            organization = request.user.organization_id

            # Get the default currency for the organization
            default_currency = OrganizationCurrency.objects.filter(
                organization=organization,
                is_default=True,
            ).first()

            assets_payload = validated_data.pop("assets", [])
            payment_type = validated_data.get("payment_type")
            jewelry_production = validated_data.get("jewelry_production")
            asset_allocation_for_production_payment = validated_data.pop(
                "asset_allocation_for_production_payment", []
            )
            self.store_current_metal_price_of_product(
                jewelry_production.manufacturing_request, default_currency
            )

            # Calculate correction amount (if any) for the production
            correction_amount = CorrectionValue.objects.filter(
                manufacturing_request=jewelry_production.manufacturing_request
            ).aggregate(total=Sum("amount"))["total"] or Decimal(0)

            stone_amount = Decimal(0)

            # ----------------------------
            # CASE 1: CASH-based payments
            # ----------------------------
            if payment_type == MaterialSource.CASH:
                manufacturing_target = ManufacturingTarget.objects.filter(
                    manufacturing_request=jewelry_production.manufacturing_request,
                )

                # Metal price
                metal_targets = manufacturing_target.filter(
                    material_type=MaterialType.METAL
                )
                metal_summary = defaultdict(Decimal)

                for metal in metal_targets:
                    key = (metal.material_item_id, metal.carat_type_id)
                    metal_summary[key] = {
                        "material_item": metal.material_item,
                        "carat_type": metal.carat_type,
                        "weight": Decimal(0),
                    }
                    metal_summary[key]["weight"] += metal.weight

                metal_amount = self.get_live_metal_price(
                    metal_summary, default_currency
                )

                # Stone price
                stone_targets = manufacturing_target.filter(
                    material_type=MaterialType.STONE
                )

                # Build total quantity map
                total_quantity_map = {}
                for target in stone_targets:
                    key = (target.material_item.id, target.shape_cut.id, target.weight)
                    total_quantity_map[key] = (
                        total_quantity_map.get(key, 0) + target.quantity
                    )

                # Get stone price records for this production
                stone_prices = JewelryProductStonePrice.objects.filter(
                    jewelry_production=jewelry_production
                )

                # Calculate total stone amount
                stone_amount = 0
                for sp in stone_prices:
                    key = (sp.material_item.id, sp.shape_cut.id, sp.weight)
                    quantity = total_quantity_map.get(key, 0)
                    if sp.stone_price is not None:
                        stone_amount += quantity * sp.stone_price

                # Compute total base amount
                base_amount = metal_amount + stone_amount + correction_amount

                # Apply VAT and platform fee
                vat, platform_fee, total_amount = self._compute_tax_fees(
                    base_amount, organization
                )

                validated_data.update(
                    {
                        "metal_amount": metal_amount,
                        "total_amount": total_amount,
                        "stone_amount": stone_amount,
                        "correction_amount": correction_amount,
                        "platform_fee": platform_fee,
                        "vat": vat,
                    }
                )

            validated_data["correction_amount"] = correction_amount
            validated_data["created_by"] = request.user
            production_payment = ProductionPayment.objects.create(**validated_data)
            jewelry_production.is_payment_completed = True
            jewelry_production.save()

            # Fetch and create ProductionPaymentAssetAllocation using Musharakah History
            if asset_allocation_for_production_payment:
                musharakah_contract = validated_data.get("musharakah_contract")

                units_to_create = []

                for unit_data in asset_allocation_for_production_payment:
                    unit_id = unit_data["precious_item_unit"]
                    weight = unit_data.get(
                        "weight"
                    )  # Weight may be provided or calculated

                    # 1. Find the correct PreciousItemUnitMusharakahHistory entry
                    history = (
                        PreciousItemUnitMusharakahHistory.objects.filter(
                            precious_item_unit_id=unit_id,
                            musharakah_contract=musharakah_contract,
                        )
                        .order_by("-created_at")
                        .first()
                    )

                    # Fetch PreciousItemUnit to calculate weight if not provided
                    precious_item_unit = None
                    if not history:
                        precious_item_unit = (
                            PreciousItemUnit.objects.filter(id=unit_id)
                            .select_related(
                                "purchase_request__precious_item__precious_metal",
                                "purchase_request__precious_item__precious_stone",
                            )
                            .first()
                        )

                    # Calculate weight if not provided
                    if weight is None:
                        if precious_item_unit and precious_item_unit.purchase_request:
                            precious_item = (
                                precious_item_unit.purchase_request.precious_item
                            )
                            if precious_item.material_type == MaterialType.METAL:
                                # For metals, use remaining_weight or full weight
                                weight = precious_item_unit.remaining_weight or (
                                    precious_item.precious_metal.weight
                                    if precious_item.precious_metal
                                    else Decimal("0.00")
                                )
                            elif precious_item.material_type == MaterialType.STONE:
                                # For stones, use the stone weight
                                weight = (
                                    precious_item.precious_stone.weight
                                    if precious_item.precious_stone
                                    else Decimal("0.00")
                                )
                            else:
                                weight = Decimal("0.00")
                        else:
                            weight = Decimal("0.00")

                    if not history:
                        units_to_create.append(
                            ProductionPaymentAssetAllocation(
                                production_payment=production_payment,
                                precious_item_unit_asset=precious_item_unit,
                                weight=weight,
                            )
                        )
                    else:
                        # 2. Prepare object for bulk_create
                        units_to_create.append(
                            ProductionPaymentAssetAllocation(
                                production_payment=production_payment,
                                precious_item_unit_musharakah=history,
                                weight=weight,
                                musharakah_contract=musharakah_contract,
                            )
                        )

                # 3. Bulk create (optimized)
                ProductionPaymentAssetAllocation.objects.bulk_create(units_to_create)

            # ----------------------------
            # CASE 2: ASSET-based payments
            # ----------------------------
            if payment_type == MaterialSource.ASSET:
                self._handle_asset_payment(
                    production_payment,
                    assets_payload,
                    business,
                    request.user,
                    correction_amount,
                    organization,
                    default_currency,
                    payment_type,
                )

            # ----------------------------
            # CASE 3: MUSHARAKAH-based payments
            # ----------------------------
            elif payment_type == MaterialSource.MUSHARAKAH:
                self._handle_musharakah_payment(
                    production_payment,
                    validated_data["musharakah_contract"],
                    correction_amount,
                    organization,
                    default_currency,
                    payment_type,
                )

            # ----------------------------
            # CASE 4: MUSHARAKAH + ASSET payments
            # ----------------------------
            elif payment_type == MaterialSource.MUSHARAKAH_AND_ASSET:
                self.store_current_metal_price_of_additional_material(
                    jewelry_production.manufacturing_request, default_currency
                )

                self._handle_musharakah_and_asset_payment(
                    production_payment,
                    validated_data["musharakah_contract"],
                    assets_payload,
                    correction_amount,
                    organization,
                    default_currency,
                    payment_type,
                    business,
                    request.user,
                )

            # Determine platform fee rate (only if type is percentage)
            platform_fee_rate = (
                organization.platform_fee_rate
                if organization.platform_fee_type == PlatformFeeType.PERCENTAGE
                else None
            )

            # Create the transaction record
            production_payment_transaction = Transaction.objects.create(
                from_business=business,
                to_business=jewelry_production.manufacturer,
                jewelry_production=jewelry_production,
                platform_fee_rate=platform_fee_rate,
                platform_fee=production_payment.platform_fee,
                vat_rate=organization.vat_rate,
                vat=production_payment.vat,
                amount=production_payment.total_amount,
                transaction_type=TransactionType.PAYMENT,
                status=TransactionStatus.SUCCESS,
                created_by=request.user,
            )
            production_payment_transaction.save()

            # Update wallet balance of manufacturer and jeweler
            wallet = Wallet.objects
            jeweler_business_wallet = wallet.filter(business=business).first()
            manufacturer_business_wallet = wallet.filter(
                business=jewelry_production.manufacturer
            ).first()

            # Calculate amounts already hold or pending for withdrawal
            total_hold_amount_for_purchase_request = get_total_hold_amount_for_investor(
                business
            )

            total_withdrawal_pending_amount = get_total_withdrawal_pending_amount(
                business
            )

            # Check for sufficient balance
            available_balance = (
                jeweler_business_wallet.balance
                - total_hold_amount_for_purchase_request
                - total_withdrawal_pending_amount
            )

            # Ensure jeweler has sufficient funds
            if available_balance < production_payment.total_amount:
                raise serializers.ValidationError(
                    INVESTOR_MESSAGES["insufficient_balance"]
                )

            # Update balances for both jeweler and manufacturer
            jeweler_business_wallet.balance -= production_payment.total_amount
            jeweler_business_wallet.save()

            # Calculate the total amount to credit to the manufacturer's wallet,
            # including metal, stone, and correction amount
            total_manufacturer_credit_amount = (
                Decimal(production_payment.metal_amount)
                + Decimal(production_payment.stone_amount)
                + Decimal(production_payment.correction_amount)
            )

            manufacturer_business_wallet.balance += total_manufacturer_credit_amount
            manufacturer_business_wallet.save()

            return production_payment

    def _validate_asset_requirements(self, asset_data, jewelry_production):
        """
        Validate that the asset contributions (metal/stone) fulfill
        the required material quantities for this production.
        For metals, carat_type is ignored to allow allocation of any carat_type material.
        """

        # Get required material weights based on manufacturing quantity
        required_materials = ManufacturingTarget.objects.filter(
            manufacturing_request=jewelry_production.manufacturing_request
        )

        # Build requirement key map (with carat_type for tracking)
        required_map = {}
        for material in required_materials:
            if material.material_type == MaterialType.METAL:
                key = (
                    material.material_type,
                    material.material_item_id,
                    material.carat_type_id,
                )
                required_map[key] = material.weight
            else:  # Stone
                if material.color:  # only for diamond
                    key = (
                        material.material_type,
                        material.material_item_id,
                        material.shape_cut_id,
                        material.weight,
                        material.clarity_id,
                        material.color_id,
                    )
                else:
                    key = (
                        material.material_type,
                        material.material_item_id,
                        material.shape_cut_id,
                        material.weight,
                    )
                required_map[key] = material.quantity

        # Prepare contributions from submitted asset data
        # For metals, use only material_type and material_item_id (ignore carat_type)
        contributed_map = defaultdict(Decimal)

        # Extract purchase request IDs - handle both string IDs and PurchaseRequest objects
        purchase_request_ids = []
        for asset in asset_data:
            purchase_request = asset.get("purchase_request")
            if isinstance(purchase_request, str):
                # If it's a string ID, use it directly
                purchase_request_ids.append(purchase_request)
            elif hasattr(purchase_request, "id"):
                # If it's a PurchaseRequest object, get its ID
                purchase_request_ids.append(purchase_request.id)
            else:
                # If it's already an ID (integer/string), use it directly
                purchase_request_ids.append(purchase_request)

        # Bulk fetch purchase requests
        purchase_requests = PurchaseRequest.objects.select_related(
            "precious_item__material_item",
            "precious_item__carat_type",
            "precious_item__precious_metal",
            "precious_item__precious_stone__shape_cut",
        ).in_bulk(purchase_request_ids)

        for asset in asset_data:
            # Get purchase request ID - handle both string IDs and PurchaseRequest objects
            purchase_request = asset.get("purchase_request")
            if isinstance(purchase_request, str):
                pr_id = purchase_request
            elif hasattr(purchase_request, "id"):
                pr_id = purchase_request.id
            else:
                pr_id = purchase_request

            pr = purchase_requests.get(pr_id)
            if not pr:
                raise serializers.ValidationError(
                    JEWELER_MESSAGES["invalid_purchase_request"]
                )

            item = pr.precious_item
            qty = Decimal(asset["quantity"])

            if item.material_type == MaterialType.METAL:
                # For metals, use only material_type and material_item_id (ignore carat_type)
                asset_key = (item.material_type, item.material_item_id)
                weight = (
                    item.precious_metal.weight if item.precious_metal else Decimal(0)
                )
                contributed_map[asset_key] += qty * weight

            elif item.material_type == MaterialType.STONE:
                if item.precious_stone.color:
                    key = (
                        item.material_type,
                        item.material_item_id,
                        item.precious_stone.shape_cut_id,
                        item.precious_stone.weight,
                        item.precious_stone.clarity_id,
                        item.precious_stone.color_id,
                    )
                else:
                    key = (
                        item.material_type,
                        item.material_item_id,
                        item.precious_stone.shape_cut_id,
                        item.precious_stone.weight,
                    )
                contributed_map[key] += qty

            else:
                raise serializers.ValidationError(
                    JEWELER_MESSAGES["invalid_material_type"]
                )

        # Check each required material is fulfilled
        # For metals, aggregate requirements by material_type + material_item_id (ignore carat_type)
        aggregated_required_map = defaultdict(Decimal)
        for key, required in required_map.items():
            if len(key) >= 3 and key[0] == MaterialType.METAL:
                # For metals, aggregate by material_type + material_item_id
                aggregated_key = (key[0], key[1])
                aggregated_required_map[aggregated_key] += required
            else:
                # For stones, keep original key
                aggregated_required_map[key] = required

        # Validate contributions against aggregated requirements
        for key, required in aggregated_required_map.items():
            contributed = contributed_map.get(key, Decimal(0)).quantize(Decimal("0.00"))
            required = Decimal(required or 0).quantize(Decimal("0.00"))

            if contributed < required:
                raise serializers.ValidationError(
                    JEWELER_MESSAGES["insufficient_contribution_for_material"]
                )

    def _validate_musharakah_and_asset_requirements(
        self, asset_data, jewelry_production
    ):
        """
        Validate that the asset contributions (metal/stone) fulfill
        the required material quantities for this production.
        For metals, carat_type is ignored to allow allocation of any carat_type material.
        """

        # Get required material weights based on manufacturing quantity
        required_materials = ManufacturingTarget.objects.filter(
            manufacturing_request=jewelry_production.manufacturing_request
        )

        # Build requirement key map (with carat_type for tracking)
        required_map = {}
        for material in required_materials:
            if material.material_type == MaterialType.METAL:
                key = (
                    material.material_type,
                    material.material_item_id,
                    material.carat_type_id,
                )
                required_map[key] = material.additional_material
            else:  # Stone
                if material.color:  # only for diamond
                    key = (
                        material.material_type,
                        material.material_item_id,
                        material.shape_cut_id,
                        material.weight,
                        material.clarity_id,
                        material.color_id,
                    )
                else:
                    key = (
                        material.material_type,
                        material.material_item_id,
                        material.shape_cut_id,
                        material.weight,
                    )
                required_map[key] = material.additional_material

        # Prepare contributions from submitted asset data
        # For metals, use only material_type and material_item_id (ignore carat_type)
        contributed_map = defaultdict(Decimal)

        # Bulk fetch purchase requests
        purchase_requests = PurchaseRequest.objects.select_related(
            "precious_item__material_item",
            "precious_item__carat_type",
            "precious_item__precious_metal",
            "precious_item__precious_stone__shape_cut",
        ).in_bulk([a["purchase_request"].id for a in asset_data])

        for asset in asset_data:
            pr = purchase_requests.get(asset["purchase_request"].id)
            if not pr:
                raise serializers.ValidationError(
                    JEWELER_MESSAGES["invalid_purchase_request"]
                )

            item = pr.precious_item
            qty = Decimal(asset["quantity"])

            if item.material_type == MaterialType.METAL:
                # For metals, use only material_type and material_item_id (ignore carat_type)
                asset_key = (item.material_type, item.material_item_id)
                weight = (
                    item.precious_metal.weight if item.precious_metal else Decimal(0)
                )
                contributed_map[asset_key] += qty * weight

            elif item.material_type == MaterialType.STONE:
                if item.precious_stone.color:
                    key = (
                        item.material_type,
                        item.material_item_id,
                        item.precious_stone.shape_cut_id,
                        item.precious_stone.weight,
                        item.precious_stone.clarity_id,
                        item.precious_stone.color_id,
                    )
                else:
                    key = (
                        item.material_type,
                        item.material_item_id,
                        item.precious_stone.shape_cut_id,
                        item.precious_stone.weight,
                    )
                contributed_map[key] += qty

            else:
                raise serializers.ValidationError(
                    JEWELER_MESSAGES["invalid_material_type"]
                )

        # Check each required material is fulfilled
        # For metals, aggregate requirements by material_type + material_item_id (ignore carat_type)
        aggregated_required_map = defaultdict(Decimal)
        for key, required in required_map.items():
            if len(key) >= 3 and key[0] == MaterialType.METAL:
                # For metals, aggregate by material_type + material_item_id
                aggregated_key = (key[0], key[1])
                aggregated_required_map[aggregated_key] += required
            else:
                # For stones, keep original key
                aggregated_required_map[key] = required

        # Validate contributions against aggregated requirements
        for key, required in aggregated_required_map.items():
            contributed = contributed_map.get(key, Decimal(0)).quantize(Decimal("0.00"))
            required = Decimal(required or 0).quantize(Decimal("0.00"))
            if contributed < required:
                raise serializers.ValidationError(
                    JEWELER_MESSAGES["insufficient_contribution_for_material"]
                )

    def _compute_tax_fees(self, base_amount, organization):
        """Compute VAT and platform fee based on organization configuration."""
        vat_amount = base_amount * organization.vat_rate
        platform_fee = calculate_platform_fee(base_amount, organization)
        total = base_amount + vat_amount + platform_fee
        return vat_amount, platform_fee, total

    def _handle_asset_payment(
        self,
        production_payment,
        assets,
        business,
        user,
        correction_amount,
        organization,
        currency_obj,
        payment_type,
    ):
        """Handle creation and pricing logic when payment is made using assets."""
        for asset in assets:
            AssetContribution.objects.create(
                purchase_request=asset["purchase_request"],
                quantity=asset["quantity"],
                business=business,
                contribution_type=ContributionType.PRODUCTION_PAYMENT,
                production_payment=production_payment,
                created_by=user,
            )

        metal_summary, stone_total = self._summarize_asset_weights(assets)
        metal_price = self.get_live_metal_price(metal_summary, currency_obj)

        if payment_type == MaterialSource.MUSHARAKAH_AND_ASSET:
            return metal_price, stone_total

        base_amount = metal_price + stone_total + correction_amount
        vat, platform_fee, total = self._compute_tax_fees(base_amount, organization)

        production_payment.total_amount = vat + platform_fee + correction_amount
        production_payment.vat = vat
        production_payment.platform_fee = platform_fee
        production_payment.save()

    def _handle_musharakah_payment(
        self,
        production_payment,
        musharakah_contract,
        correction_amount,
        organization,
        currency_obj,
        payment_type,
    ):
        """Handle total computation when payment is made using Musharakah assets."""
        metal_summary = defaultdict(Decimal)
        stone_total = Decimal(0)

        payment_unit = production_payment.payment_units.values_list(
            "precious_item_unit_musharakah__precious_item_unit__purchase_request_id",
            "precious_item_unit_asset__purchase_request_id",
        )

        purchase_request_ids = {
            musharakah_id or asset_id
            for musharakah_id, asset_id in payment_unit
            if (musharakah_id or asset_id) is not None
        }

        # Fetch asset contributions from the Musharakah contract request that
        # match the collected purchase request IDs.
        musharakah_assets = AssetContribution.objects.select_related(
            "purchase_request__precious_item__material_item",
            "purchase_request__precious_item__carat_type",
            "purchase_request__precious_item__precious_metal",
        ).filter(
            musharakah_contract_request=musharakah_contract,
            purchase_request_id__in=purchase_request_ids,
        )

        for asset in musharakah_assets:
            item = asset.purchase_request.precious_item
            qty = Decimal(asset.quantity)

            if item.material_type == MaterialType.METAL:
                weight_per_unit = (
                    item.precious_metal.weight if item.precious_metal else Decimal(0)
                )
                weight = qty * weight_per_unit
                key = (item.material_item_id, item.carat_type_id)

                if key not in metal_summary:
                    metal_summary[key] = {
                        "material_item": item.material_item,
                        "carat_type": item.carat_type,
                        "weight": Decimal(0),
                    }
                metal_summary[key]["weight"] += weight
            else:
                stone_total += asset.purchase_request.price_locked or Decimal(0)

        metal_price = self.get_live_metal_price(metal_summary, currency_obj)

        if payment_type == MaterialSource.MUSHARAKAH_AND_ASSET:
            return metal_price, stone_total

        base_amount = metal_price + stone_total + correction_amount
        vat, platform_fee, total = self._compute_tax_fees(base_amount, organization)

        production_payment.total_amount = vat + platform_fee + correction_amount
        production_payment.vat = vat
        production_payment.platform_fee = platform_fee
        production_payment.save()

    def _handle_musharakah_and_asset_payment(
        self,
        production_payment,
        musharakah_contract,
        assets_payload,
        correction_amount,
        organization,
        currency_obj,
        payment_type,
        business,
        user,
    ):
        """Combine both Musharakah and Asset contributions into final total."""
        (
            musharakah_metal_price,
            musharakah_stone_price,
        ) = self._handle_musharakah_payment(
            production_payment,
            musharakah_contract,
            correction_amount,
            organization,
            currency_obj,
            payment_type,
        )

        asset_metal_price, asset_stone_price = self._handle_asset_payment(
            production_payment,
            assets_payload,
            business,
            user,
            correction_amount,
            organization,
            currency_obj,
            payment_type,
        )

        base_amount = (
            musharakah_metal_price
            + musharakah_stone_price
            + asset_metal_price
            + asset_stone_price
            + correction_amount
        )
        vat, platform_fee, total = self._compute_tax_fees(base_amount, organization)

        production_payment.total_amount = vat + platform_fee + correction_amount
        production_payment.vat = vat
        production_payment.platform_fee = platform_fee
        production_payment.save()

    def _summarize_asset_weights(self, asset_data):
        """Summarize total metal weights and stone price from provided asset data."""
        metal_summary = defaultdict(Decimal)
        stone_total = Decimal(0)

        purchase_requests = PurchaseRequest.objects.select_related(
            "precious_item__material_item",
            "precious_item__carat_type",
            "precious_item__precious_metal",
        ).in_bulk([a["purchase_request"].id for a in asset_data])

        for asset in asset_data:
            pr = purchase_requests.get(asset["purchase_request"].id)
            item = pr.precious_item
            qty = Decimal(asset["quantity"])

            if item.material_type == MaterialType.METAL:
                weight_per_unit = (
                    item.precious_metal.weight if item.precious_metal else Decimal(0)
                )
                weight = qty * weight_per_unit
                key = (item.material_item_id, item.carat_type_id)
                if key not in metal_summary:
                    metal_summary[key] = {
                        "material_item": item.material_item,
                        "carat_type": item.carat_type,
                        "weight": Decimal(0),
                    }
                metal_summary[key]["weight"] += weight
            else:
                stone_total += pr.price_locked or Decimal(0)

        return metal_summary, stone_total

    def store_current_metal_price_of_additional_material(
        self, manufacturing_request, currency_rate
    ):
        manufacturing_target = ManufacturingTarget.objects.filter(
            manufacturing_request=manufacturing_request,
            material_type=MaterialType.METAL,
        )

        # Create a dict of indexed assets (required by get_live_metal_price)
        additional_material_data = {}

        for idx, target in enumerate(manufacturing_target):
            additional_material_data[idx] = {
                "material_item": target.material_item,
                "carat_type": target.carat_type,
                "weight": target.additional_material,
            }

        # Calculate live price for each target individually
        for idx, target in enumerate(manufacturing_target):
            asset = additional_material_data[idx]

            # Pass a SINGLE asset wrapped in a dict because get_live_metal_price expects dict-of-dicts
            live_price = self.get_live_metal_price(
                {idx: asset}, currency_rate  # valid structure for the function
            )

            target.metal_amount = live_price
            target.save(update_fields=["metal_amount"])

    def store_current_metal_price_of_product(
        self, manufacturing_request, currency_rate
    ):
        """Store live metal price for each product in the manufacturing request."""

        manufacturing_products = ManufacturingProductRequestedQuantity.objects.filter(
            manufacturing_request=manufacturing_request
        )

        for product in manufacturing_products:
            # ← return queryset (NOT .first)
            metal_materials = product.jewelry_product.product_materials.filter(
                material_type=MaterialType.METAL
            )

            # Ensure queryset is not empty
            if not metal_materials.exists():
                continue

            # Pass queryset as expected by get_live_metal_price
            live_price = self.get_metal_price(metal_materials, currency_rate)
            product.metal_amount = live_price
            product.save(update_fields=["metal_amount"])

    def get_metal_price(self, assets, currency_rate):
        """Fetch real-time price for contributed metals and compute total value."""

        if not assets.exists():
            return Decimal(0)

        # preload related FK to avoid N+1 queries
        assets = assets.select_related("material_item", "carat_type")

        # extract global_metal ids
        global_metals = [a.material_item.global_metal_id for a in assets]

        latest_prices_qs = (
            MetalPriceHistory.objects.filter(global_metal_id__in=global_metals)
            .order_by("global_metal_id", "-created_at")
            .distinct("global_metal_id")
        )

        # lookup table
        latest_prices = {mp.global_metal_id: mp.price for mp in latest_prices_qs}

        total_metal_price = Decimal(0)

        for asset in assets:
            metal_price = latest_prices.get(asset.material_item.global_metal_id)

            if not metal_price:
                continue

            carat = asset.carat_type
            weight = asset.weight

            # 22k → 22
            carat_number = int(carat.name.rstrip("k"))

            # purity adjusted price
            price_per_unit = (carat_number * metal_price) / 24

            contribution = Decimal(price_per_unit) * weight * currency_rate.rate

            total_metal_price += contribution

        total_rounded = round(total_metal_price, 2)

        return total_rounded

    def get_live_metal_price(self, assets, currency_rate):
        """Fetch real-time price for contributed metals and compute total value."""

        if not assets:
            return Decimal(0)
        # Get distinct latest prices for all metals in one query
        latest_prices_qs = (
            MetalPriceHistory.objects.filter(
                global_metal__in=[
                    a["material_item"].global_metal for a in assets.values()
                ]
            )
            .order_by("global_metal", "-created_at")
            .distinct("global_metal")  # Postgres DISTINCT ON
        )

        # Build lookup dict {global_metal_id: price}
        latest_prices = {mp.global_metal_id: mp.price for mp in latest_prices_qs}

        total_metal_price = Decimal(0)

        # Iterate over values (dicts), not keys (tuples)
        for asset in assets.values():
            material_item = asset["material_item"]
            carat_type = asset["carat_type"]
            weight = asset["weight"]

            metal_price = latest_prices.get(material_item.global_metal_id)
            if not metal_price:
                continue

            # Example: 22k -> 22
            carat_number = int(carat_type.name.rstrip("k"))

            # Price adjusted for purity
            price_per_unit = (carat_number * metal_price) / 24

            total_metal_price += Decimal(price_per_unit) * weight * currency_rate.rate

        return round(total_metal_price, 2)


class JewelryDesignCollectionNameSerializer(serializers.Serializer):
    """Serializer to validate if a collection name already exists."""

    collection_name = serializers.CharField(required=True, max_length=255)

    def validate_collection_name(self, value):
        """Validate that collection name is not empty or whitespace-only."""
        if value:
            # Strip whitespace from the value
            stripped_value = value.strip()
            # Check if the stripped value is empty
            if not stripped_value:
                raise serializers.ValidationError(
                    JEWELER_MESSAGES["collection_name_cannot_be_empty"]
                )
            # Return the stripped value
            return stripped_value
        # If value is None or empty, raise validation error
        raise serializers.ValidationError(
            JEWELER_MESSAGES["collection_name_cannot_be_empty"]
        )


class DashboardInsightSerializer(serializers.Serializer):
    total_metal_quantity = serializers.IntegerField()
    total_stone_quantity = serializers.IntegerField()
    total_quantity = serializers.IntegerField()


class MusharakahContractManufacturingRequestSerializer(serializers.ModelSerializer):
    """Serializer for used manufacturing request in which musharakah contract is used fir payment"""

    manufacturing_product_requested_quantities = (
        ManufacturingProductRequestedQuantityResponseSerializer(many=True)
    )
    manufacturing_estimation = SerializerMethodField()

    class Meta:
        model = ManufacturingRequest
        fields = [
            "id",
            "manufacturing_product_requested_quantities",
            "status",
            "manufacturing_estimation",
        ]

    def get_manufacturing_estimation(self, obj):
        """Get the accepted manufacturing estimation for this request."""
        from sooq_althahab.enums.manufacturer import ManufactureRequestStatus

        estimation = (
            obj.estimation_requests.filter(status=ManufactureRequestStatus.ACCEPTED)
            .order_by("-created_at")
            .first()
        )

        if estimation:
            return ManufacturingEstimationRequestResponseSerializer(estimation).data
        return None

    def to_representation(self, instance):
        """Override to pass musharakah_contract context to nested serializers."""
        representation = super().to_representation(instance)

        # Get musharakah_contract from context
        musharakah_contract = self.context.get("musharakah_contract")

        # Serialize manufacturing_product_requested_quantities with context
        # This ensures profit calculation has access to musharakah_contract
        quantities_data = []
        for quantity_obj in instance.manufacturing_product_requested_quantities.all():
            # Create a new context that includes both existing context and musharakah_contract
            quantity_context = dict(self.context)
            if musharakah_contract:
                quantity_context["musharakah_contract"] = musharakah_contract

            serializer = ManufacturingProductRequestedQuantityResponseSerializer(
                quantity_obj, context=quantity_context
            )
            quantities_data.append(serializer.data)
        representation["manufacturing_product_requested_quantities"] = quantities_data

        return representation


class MusharakahContractRequestRetrieveSerializer(
    MusharakahContractRequestResponseSerializer
):
    """Extended serializer to include contract_details for retrieve view."""

    contract_details = SerializerMethodField()
    manufacturing_requests = SerializerMethodField()
    unsold_jewelry_count = SerializerMethodField()
    completion_level = SerializerMethodField()
    musharakah_contract_profit = serializers.CharField(default=Decimal("0.00"))
    musharakah_contract_profit = SerializerMethodField()

    class Meta(MusharakahContractRequestResponseSerializer.Meta):
        pass  # reuse fields & exclusions

    def get_contract_details(self, obj):
        request = self.context.get("request")
        html = generate_contract_details_html(obj, request)
        return html.replace("\n", "")

    def get_manufacturing_requests(self, obj):
        """Get all manufacturing requests that use this musharakah contract through production payments."""
        production_payments = ProductionPayment.objects.filter(
            musharakah_contract=obj, deleted_at__isnull=True
        ).select_related("jewelry_production__manufacturing_request")

        manufacturing_requests_data = []
        for payment in production_payments:
            if (
                payment.jewelry_production
                and payment.jewelry_production.manufacturing_request
            ):
                manufacturing_request = payment.jewelry_production.manufacturing_request
                manufacturing_request_data = (
                    MusharakahContractManufacturingRequestSerializer(
                        manufacturing_request, context={"musharakah_contract": obj}
                    ).data
                )
                manufacturing_requests_data.append(manufacturing_request_data)

        return manufacturing_requests_data

    def get_unsold_jewelry_count(self, obj):
        payments = ProductionPayment.objects.filter(musharakah_contract=obj)

        total_unsold_jewelry_count = 0
        for payment in payments:
            production = payment.jewelry_production

            total_product = (
                ManufacturingProductRequestedQuantity.objects.filter(
                    manufacturing_request=production.manufacturing_request
                )
                .select_related("jewelry_product")
                .aggregate(
                    total_quantity=Sum("quantity"),
                )
            )
            total_unsold_jewelry_count += total_product.get("total_quantity") or 0

        return total_unsold_jewelry_count

    def get_completion_level(self, obj):
        return get_musharakah_contract_jewelry_product_count(obj)

    def get_musharakah_contract_profit(self, obj):
        request = self.context.get("request")
        business = get_business_from_user_token(request, "business")
        profit = JewelryProfitDistribution.objects.filter(
            musharakah_contract=obj, recipient_business=business
        ).aggregate(total=Sum("profit_amount"))["total"] or Decimal("0.00")
        return profit


class SettlementSummaryPaymentSerializer(serializers.Serializer):
    musharakah_contract_id = serializers.CharField(write_only=True, required=True)


class AddDesignsToCollectionSerializer(serializers.Serializer):
    """Serializer for adding SINGLE designs to a COLLECTION."""

    collection_id = serializers.CharField(
        required=True, help_text="ID of the collection to add designs to"
    )
    single_design_ids = serializers.ListField(
        child=serializers.CharField(),
        required=True,
        allow_empty=False,
        help_text="List of SINGLE design IDs to add to the collection",
    )
