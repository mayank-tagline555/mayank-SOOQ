from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

from jeweler.models import JewelryProductInspectionAttachment
from jeweler.models import JewelryProduction
from jeweler.models import JewelryProductStonePrice
from jeweler.models import ManufacturingProductRequestedQuantity
from jeweler.models import ManufacturingRequest
from jeweler.models import ProductionPayment
from jeweler.models import ProductionPaymentAssetAllocation
from jeweler.serializers import ManufacturingProductRequestedQuantityResponseSerializer
from jeweler.serializers import ManufacturingTargetSerializer
from sooq_althahab.enums.account import UserRoleBusinessChoices
from sooq_althahab.enums.jeweler import DesignType
from sooq_althahab.enums.jeweler import InspectionStatus
from sooq_althahab.enums.jeweler import JewelryProductAttachmentUploadedByChoices
from sooq_althahab.enums.jeweler import ManufactureType
from sooq_althahab.enums.jeweler import ManufacturingStatus
from sooq_althahab.enums.jeweler import ProductionStatus
from sooq_althahab.enums.jeweler import ProductProductionStatus
from sooq_althahab.enums.jeweler import RequestStatus
from sooq_althahab.enums.manufacturer import ManufactureRequestStatus
from sooq_althahab.querysets.purchase_request import get_business_from_user_token
from sooq_althahab.utils import get_presigned_url_from_s3

from .message import MESSAGES as MANUFACTURER_MESSAGE
from .models import CorrectionValue
from .models import ManufacturingEstimationRequest
from .models import ProductManufacturingEstimatedPrice


class ProductManufacturingEstimatedPriceSerializer(serializers.ModelSerializer):
    """Serializer for the ProductManufacturingEstimatedPrice model."""

    class Meta:
        model = ProductManufacturingEstimatedPrice
        fields = [
            "id",
            "requested_product",
            "estimated_price",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ManufacturingEstimationRequestSerializer(serializers.ModelSerializer):
    """Serializer for the Manufacturing Estimation Request model."""

    product_manufacturing_estimated_request = (
        ProductManufacturingEstimatedPriceSerializer(many=True, write_only=True)
    )

    class Meta:
        model = ManufacturingEstimationRequest
        fields = [
            "id",
            "manufacturing_request",
            "status",
            "duration",
            "comment",
            "created_at",
            "updated_at",
            "product_manufacturing_estimated_request",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "status"]

    def create(self, validated_data):
        """Create a new Manufacturing Estimation Request instance."""

        request = self.context["request"]
        product_manufacturing_estimated_request = validated_data.pop(
            "product_manufacturing_estimated_request"
        )

        business = get_business_from_user_token(request, "business")
        estimation_request = ManufacturingEstimationRequest.objects.create(
            business=business,
            created_by=request.user,
            organization_id=request.user.organization_id,
            **validated_data
        )

        ProductManufacturingEstimatedPrice.objects.bulk_create(
            [
                ProductManufacturingEstimatedPrice(
                    estimation_request=estimation_request,
                    organization_id=request.user.organization_id,
                    created_by=request.user,
                    **estimate
                )
                for estimate in product_manufacturing_estimated_request
            ]
        )
        estimation_request.manufacturing_request.status = (
            ManufacturingStatus.QUOTATION_SUBMITTED
        )
        estimation_request.manufacturing_request.save()
        return estimation_request


class ManufacturingEstimationRequestResponseSerializer(serializers.ModelSerializer):
    """Serializer for the Manufacturing Estimation Request model."""

    estimated_prices = ProductManufacturingEstimatedPriceSerializer(many=True)
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = ManufacturingEstimationRequest
        fields = [
            "id",
            "manufacturing_request",
            "status",
            "duration",
            "comment",
            "created_at",
            "updated_at",
            "created_by",
            "estimated_prices",
        ]

    def get_created_by(self, obj):
        data = {
            "id": obj.created_by.id,
            "name": obj.created_by.fullname,
            "profile_url": get_presigned_url_from_s3(obj.created_by.profile_image),
        }
        return data


class ManufacturingRequestSerializer(serializers.ModelSerializer):
    """Serializer for manufacturing requests."""

    manufacturing_product_requested_quantities = (
        ManufacturingProductRequestedQuantityResponseSerializer(many=True)
    )
    manufacturing_targets = ManufacturingTargetSerializer(many=True)
    created_by = serializers.SerializerMethodField()
    business = serializers.SerializerMethodField()
    correction_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    manufacturing_estimation = serializers.SerializerMethodField()

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
        data = {
            "id": obj.business.id,
            "name": obj.business.name,
            "logo": get_presigned_url_from_s3(obj.business.logo),
        }
        return data

    def get_created_by(self, obj):
        data = {
            "id": obj.created_by.id,
            "name": obj.created_by.fullname,
            "profile_url": get_presigned_url_from_s3(obj.created_by.profile_image),
        }
        return data

    def get_manufacturing_estimation(self, obj):
        estimation = (
            obj.estimation_requests.filter(status=ManufactureRequestStatus.ACCEPTED)
            .order_by("-created_at")
            .first()
        )
        if estimation:
            return ManufacturingEstimationRequestResponseSerializer(estimation).data
        return None


class ManufacturingRequestDetailSerializer(ManufacturingRequestSerializer):
    """Serializer for manufacturing requests."""

    estimation_requests = serializers.SerializerMethodField()
    current_user_estimation_status = serializers.SerializerMethodField()

    def get_estimation_requests(self, obj):
        business = get_business_from_user_token(self.context.get("request"), "business")
        # For manufacturers, show only their own estimation requests
        # For admins/other roles, show all estimation requests
        if (
            business
            and business.business_account_type == UserRoleBusinessChoices.MANUFACTURER
        ):
            estimations = obj.estimation_requests.filter(business=business)
        else:
            estimations = obj.estimation_requests.all()

        return ManufacturingEstimationRequestResponseSerializer(
            estimations, many=True
        ).data

    def get_current_user_estimation_status(self, obj):
        """
        Get the current user's (manufacturer's) estimation request status.
        Returns the status if they have submitted an estimation, None otherwise.
        This helps the frontend determine if the "Estimate Price" button should be shown.
        """
        business = get_business_from_user_token(self.context.get("request"), "business")
        if (
            not business
            or business.business_account_type != UserRoleBusinessChoices.MANUFACTURER
        ):
            return None

        # Get the current manufacturer's estimation request
        user_estimation = obj.estimation_requests.filter(business=business).first()
        if user_estimation:
            return user_estimation.status
        return None


class JewelryProductStonePriceSerializer(serializers.ModelSerializer):
    class Meta:
        model = JewelryProductStonePrice
        fields = [
            "id",
            "jewelry_production",
            "material_item",
            "weight",
            "shape_cut",
            "stone_price",
        ]
        read_only_fields = ["id"]


class ProductionPaymentAssetAllocationResponseSerializer(serializers.ModelSerializer):
    """
    Serializer for ProductionPaymentAssetAllocation model.

    Maps specific PreciousItemUnits (serial-numbered assets) to a Production Payment.
    Ensures traceability of which exact units were used in fulfilling
    a production payment (whether direct asset contributions or via Musharakah Contract assets).
    """

    precious_item_unit = serializers.SerializerMethodField()

    class Meta:
        model = ProductionPaymentAssetAllocation
        fields = [
            "id",
            "precious_item_unit",
            "musharakah_contract",
            "weight",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def get_precious_item_unit(self, obj):
        """Get detailed precious item unit information."""
        if obj.precious_item_unit_musharakah:
            history = obj.precious_item_unit_musharakah
            unit = history.precious_item_unit
            return {
                "id": unit.id,
                "serial_number": unit.serial_number,
                "precious_item_name": unit.precious_item.name
                if unit.precious_item
                else None,
                "material_type": unit.precious_item.material_type
                if unit.precious_item
                else None,
                "material_item": unit.precious_item.material_item.name
                if unit.precious_item and unit.precious_item.material_item
                else None,
            }
        if obj.precious_item_unit_asset:
            unit = obj.precious_item_unit_asset
            return {
                "id": unit.id,
                "serial_number": unit.serial_number,
                "precious_item_name": unit.precious_item.name
                if unit.precious_item
                else None,
                "material_type": unit.precious_item.material_type
                if unit.precious_item
                else None,
                "material_item": unit.precious_item.material_item.name
                if unit.precious_item and unit.precious_item.material_item
                else None,
            }
        return None


class ProductionPaymentResponseSerializer(serializers.ModelSerializer):
    """
    Serializer for ProductionPayment model.

    Tracks payments related to the production process including
    metal amounts, stone amounts, correction amounts, VAT, platform fees, and total amounts.
    """

    asset_serial_numbers = serializers.SerializerMethodField()
    asset_contributions = serializers.SerializerMethodField()

    class Meta:
        model = ProductionPayment
        fields = [
            "id",
            "jewelry_production",
            "musharakah_contract",
            "payment_type",
            "metal_amount",
            "stone_amount",
            "correction_amount",
            "vat",
            "platform_fee",
            "total_amount",
            "asset_serial_numbers",
            "asset_contributions",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_asset_contributions(self, obj):
        """Get asset contributions for this production payment."""
        from investor.serializers import AssetContributionSummarySerializer

        contributions = obj.asset_contributions.all()
        return AssetContributionSummarySerializer(contributions, many=True).data

    def get_asset_serial_numbers(self, obj):
        """Get asset contributions for this production payment."""

        contributions = obj.payment_units.all()
        return ProductionPaymentAssetAllocationResponseSerializer(
            contributions, many=True
        ).data


class JewelryProductionDetailSerializer(serializers.ModelSerializer):
    manufacturing_request = ManufacturingRequestSerializer()
    design = serializers.SerializerMethodField()
    stone_prices = JewelryProductStonePriceSerializer(many=True)
    payment = ProductionPaymentResponseSerializer()

    class Meta:
        model = JewelryProduction
        exclude = [
            "deleted_at",
            "restored_at",
            "transaction_id",
            "organization_id",
        ]

    def get_design(self, obj):
        design = obj.design
        if design.design_type == DesignType.SINGLE:
            # Return the first product_name for SINGLE type designs
            first_product = design.jewelry_products.first()
            return {
                "name": first_product.product_name if first_product else None,
                "design_type": design.design_type,
            }
        elif design.design_type == DesignType.COLLECTION:
            return {"name": design.name, "design_type": design.design_type}
        return None


class JewelryProductionUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = JewelryProduction
        fields = ["production_status", "delivery_date"]

    def validate(self, attrs):
        instance = self.instance
        current_production_status = instance.production_status
        new_production_status = attrs.get("production_status")
        delivery_date = attrs.get("delivery_date")

        if instance.admin_inspection_status == InspectionStatus.IN_PROGRESS:
            raise serializers.ValidationError(
                MANUFACTURER_MESSAGE["jewelry_production_inspection_in_progress"]
            )

        # Define allowed transitions
        allowed_transitions = {
            ProductionStatus.NOT_STARTED: [ProductionStatus.IN_PROGRESS],
            ProductionStatus.IN_PROGRESS: [
                ProductionStatus.ON_HOLD,
                ProductionStatus.COMPLETED,
            ],
            ProductionStatus.ON_HOLD: [ProductionStatus.IN_PROGRESS],
            ProductionStatus.COMPLETED: [ProductionStatus.IN_PROGRESS],
        }

        # Validate production_status transition
        if new_production_status and new_production_status != current_production_status:
            allowed_next_status = allowed_transitions.get(current_production_status, [])

            if new_production_status not in allowed_next_status:
                raise serializers.ValidationError(
                    MANUFACTURER_MESSAGE[
                        "jewelry_production_invalid_status_change"
                    ].format(
                        current=current_production_status.replace("_", " ").title(),
                        new=new_production_status.replace("_", " ").title(),
                    )
                )

        delivery_date = attrs.get("delivery_date")
        if delivery_date and delivery_date < timezone.now().date():
            raise serializers.ValidationError(
                MANUFACTURER_MESSAGE["delivery_date_error"]
            )

        return attrs

    def update(self, instance, validated_data):
        production_status = validated_data.get("production_status")
        delivery_date = validated_data.get("delivery_date")
        old_production_status = instance.production_status

        instance.production_status = production_status
        if delivery_date:
            instance.delivery_date = delivery_date
        is_in_progress_status = production_status == ProductionStatus.IN_PROGRESS

        if (
            is_in_progress_status
            and old_production_status == ProductionStatus.COMPLETED
        ):
            ManufacturingProductRequestedQuantity.objects.filter(
                Q(manufacturing_request=instance.manufacturing_request)
                & (
                    Q(jeweler_inspection_status=RequestStatus.REJECTED)
                    | Q(admin_inspection_status=RequestStatus.REJECTED)
                )
            ).update(
                jeweler_inspection_status=RequestStatus.PENDING,
                admin_inspection_status=RequestStatus.PENDING,
            )
            instance.admin_inspection_status = RequestStatus.PENDING
            instance.is_jeweler_approved = False

        if (
            is_in_progress_status
            and old_production_status == ProductionStatus.NOT_STARTED
        ):
            instance.started_at = timezone.now()
        elif production_status == ProductionStatus.COMPLETED:
            instance.completed_at = timezone.now()

        updated_fields = {}
        if production_status:
            updated_fields["production_status"] = True
        if delivery_date:
            updated_fields["delivery_date"] = True

        instance.updated_fields = updated_fields
        instance.save()
        return instance


class JewelryProductStatusUpdateSerializer(serializers.ModelSerializer):
    attachments = serializers.ListField(child=serializers.CharField(), required=False)

    class Meta:
        model = ManufacturingProductRequestedQuantity
        fields = ["id", "production_status", "attachments"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        instance = self.instance
        current_production_status = instance.production_status
        new_production_status = attrs.get("production_status")

        allowed_transitions = {
            ProductProductionStatus.PENDING: [ProductProductionStatus.IN_PROGRESS],
            ProductProductionStatus.IN_PROGRESS: [
                ProductProductionStatus.ON_HOLD,
                ProductProductionStatus.COMPLETED,
            ],
            ProductProductionStatus.ON_HOLD: [ProductProductionStatus.IN_PROGRESS],
            ProductProductionStatus.COMPLETED: [ProductProductionStatus.IN_PROGRESS],
        }

        # Validate production_status transition
        if new_production_status and new_production_status != current_production_status:
            allowed_next_status = allowed_transitions.get(current_production_status, [])

            if new_production_status not in allowed_next_status:
                raise serializers.ValidationError(
                    MANUFACTURER_MESSAGE[
                        "jewelry_product_invalid_status_change"
                    ].format(
                        current=current_production_status.replace("_", " ").title(),
                        new=new_production_status.replace("_", " ").title(),
                    )
                )

        return attrs

    def update(self, instance, validated_data):
        # Update production status
        request = self.context.get("request")
        instance.production_status = validated_data.get(
            "production_status", instance.production_status
        )
        instance.save(update_fields=["production_status"])

        # Handle attachments with bulk_create if provided
        attachments_data = validated_data.pop("attachments", [])
        if attachments_data:
            attachments = [
                JewelryProductInspectionAttachment(
                    file=attachment,
                    manufacturing_jewelry_product=instance,
                    uploaded_by=JewelryProductAttachmentUploadedByChoices.MANUFACTURER,
                    created_by=request.user,
                )
                for attachment in attachments_data
            ]
            JewelryProductInspectionAttachment.objects.bulk_create(attachments)

        return instance


class CorrectionValueSerializer(serializers.ModelSerializer):
    class Meta:
        model = CorrectionValue
        fields = [
            "id",
            "manufacturing_request",
            "status",
            "amount",
            "notes",
        ]
        read_only_fields = ["id", "status"]

    def validate(self, attrs):
        manufacturing_request = attrs.get("manufacturing_request")

        try:
            jewelry_production = manufacturing_request.jewelry_production
        except JewelryProduction.DoesNotExist:
            raise serializers.ValidationError(
                MANUFACTURER_MESSAGE["jewelry_production_not_found"]
            )

        # Check if payment is already completed
        if jewelry_production.is_payment_completed:
            raise serializers.ValidationError(
                MANUFACTURER_MESSAGE["correction_value_payment_already_completed"]
            )

        if jewelry_production.admin_inspection_status not in [
            InspectionStatus.COMPLETED,
            InspectionStatus.ADMIN_APPROVAL,
        ]:
            raise serializers.ValidationError(
                MANUFACTURER_MESSAGE[
                    "jewelry_inspection_status_must_be_pending_payment"
                ]
            )

        return attrs

    def create(self, validated_data):
        correction_value = CorrectionValue.objects.create(
            created_by=self.context["request"].user, **validated_data
        )
        return correction_value
