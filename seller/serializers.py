from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.serializers import CharField
from rest_framework.serializers import ChoiceField
from rest_framework.serializers import DecimalField
from rest_framework.serializers import DictField
from rest_framework.serializers import IntegerField
from rest_framework.serializers import ListField
from rest_framework.serializers import ModelSerializer
from rest_framework.serializers import Serializer
from rest_framework.serializers import SerializerMethodField
from rest_framework.serializers import ValidationError

from account.message import MESSAGES
from account.mixins import BusinessDetailsMixin
from account.models import Organization
from account.utils import calculate_platform_fee
from investor.models import AssetContribution
from investor.models import PreciousItemUnit
from investor.models import PurchaseRequest
from jeweler.serializers import JewelryProductResponseSerializer
from seller.message import MESSAGES as SELLER_MESSAGE
from sooq_althahab.enums.investor import ContributionType
from sooq_althahab.enums.investor import PurchaseRequestStatus
from sooq_althahab.enums.investor import RequestType
from sooq_althahab.enums.seller import CertificateType
from sooq_althahab.enums.seller import PremiumValueType
from sooq_althahab.enums.sooq_althahab_admin import MaterialType
from sooq_althahab.querysets.purchase_request import get_business_from_user_token
from sooq_althahab.utils import get_presigned_url_from_s3
from sooq_althahab_admin.serializers import MaterialItemDetailSerializer

from .models import PreciousItem
from .models import PreciousItemImage
from .models import PreciousMetal
from .models import PreciousStone


# Serializer for PreciousItems
class PreciousMetalSerializer(ModelSerializer):
    class Meta:
        model = PreciousMetal
        exclude = [
            "deleted_at",
            "restored_at",
            "transaction_id",
            "created_at",
            "updated_at",
            "precious_item",
        ]


class PreciousStoneSerializer(ModelSerializer):
    class Meta:
        model = PreciousStone
        exclude = [
            "deleted_at",
            "restored_at",
            "transaction_id",
            "created_at",
            "updated_at",
            "precious_item",
        ]


class CreatePreciousItemSerializer(ModelSerializer):
    """Serializer to handle creation of PreciousItem and its associated models (PreciousMetal and PreciousStone)."""

    # Fields for PreciousMetal and PreciousStone
    item_images = ListField(child=CharField(), required=False)
    precious_metal = PreciousMetalSerializer(required=False)
    precious_stone = PreciousStoneSerializer(required=False)

    class Meta:
        model = PreciousItem
        exclude = [
            "deleted_at",
            "restored_at",
            "transaction_id",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
            "organization_id",
            "business",
        ]

    def validate(self, data):
        """Ensure either `precious_metal` or `precious_stone` is provided during creation."""

        request = self.context.get("request")
        organization_code = request.auth.get("organization_code")
        business = get_business_from_user_token(request, "business")

        if not business:
            raise ValidationError(MESSAGES["business_account_not_found"])

        # Get Organization
        try:
            organization = Organization.objects.get(code=organization_code)
        except:
            raise ValidationError(MESSAGES["organization_not_found"])

        if self.instance is None:  # Only validate on create
            if not data.get("precious_metal") and not data.get("precious_stone"):
                raise ValidationError(MESSAGES["precious_metal_stone_required"])

            if data.get("material_type") == MaterialType.METAL and not data.get(
                "carat_type"
            ):
                raise ValidationError(MESSAGES["carat_type_required"])

            if data.get("precious_metal") and data.get("precious_stone"):
                raise ValidationError(MESSAGES["precious_item_one_time_error"])

            if data.get("certificate_type") == CertificateType.GIA:
                if not data.get("report_number"):
                    raise ValidationError(MESSAGES["report_number_required"])

                if not data.get("date_of_issue"):
                    raise ValidationError(MESSAGES["date_of_issue_required"])

                report_number = data.get("report_number")
                if PreciousItem.objects.filter(
                    report_number=report_number, organization_id=organization
                ).exists():
                    raise ValidationError(MESSAGES["report_number_exists"])

            premium_price_rate = data.get("premium_price_rate")
            premium_price_amount = data.get("premium_price_amount")
            premium_value_type = data.get("premium_value_type")

            # Validate premium price amount and percentage based on premium value type
            # and ensure values are greater than or equal to zero.
            if (
                premium_value_type == PremiumValueType.PERCENTAGE
                and premium_price_rate is None
            ):
                raise ValidationError(
                    SELLER_MESSAGE["premium_price_rate_required_error"]
                )

            elif (
                premium_value_type == PremiumValueType.AMOUNT
                and premium_price_amount is None
            ):
                raise ValidationError(
                    SELLER_MESSAGE["premium_price_amount_required_error"]
                )

            elif premium_value_type == PremiumValueType.BOTH and (
                not premium_price_rate or not premium_price_amount
            ):
                raise ValidationError(
                    SELLER_MESSAGE["premium_price_amount_percentage_required_error"]
                )

        # Check for existing precious items with the same metal, name, and weight
        metal_data = data.get("precious_metal")
        if metal_data:
            name = data.get("name")
            weight = metal_data.get("weight")

            if PreciousItem.objects.filter(
                material_type=MaterialType.METAL,
                name=name,
                precious_metal__weight=weight,
                business=business,
            ).exists():
                raise ValidationError(MESSAGES["metal_name_weight_exists"])

        return data

    def create(self, validated_data):
        """Create a PreciousItem with related models."""

        request = self.context.get("request")
        images_data = validated_data.pop("item_images", [])
        precious_metal_data = validated_data.pop("precious_metal", {})
        precious_stone_data = validated_data.pop("precious_stone", {})
        business = get_business_from_user_token(request, "business")

        validated_data["business"] = business
        with transaction.atomic():
            precious_item = PreciousItem.objects.create(
                **validated_data,
                created_by=request.user,
                organization_id=request.user.organization_id
            )

            if images_data:
                PreciousItemImage.objects.bulk_create(
                    [
                        PreciousItemImage(precious_item=precious_item, image=image_url)
                        for image_url in images_data
                    ]
                )

            if precious_metal_data:
                PreciousMetal.objects.create(
                    precious_item=precious_item, **precious_metal_data
                )
            elif precious_stone_data:
                PreciousStone.objects.create(
                    precious_item=precious_item, **precious_stone_data
                )

        return precious_item


class UpdatePreciousItemSerializer(CreatePreciousItemSerializer):
    """
    Serializer to handle update of PreciousItem and its associated models (PreciousMetal and PreciousStone).

    Fields:
        - deleted_image_ids: List of IDs of images to be deleted.
    """

    delete_image_ids = ListField(child=CharField(), required=False, write_only=True)

    class Meta:
        model = PreciousItem
        exclude = [
            "deleted_at",
            "restored_at",
            "transaction_id",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
            "organization_id",
            "business",
        ]

    def update(self, instance, validated_data):
        """Update a PreciousItem, keeping old values if `precious_metal` or `precious_stone` is missing."""
        request = self.context.get("request")
        images_data = validated_data.pop("item_images", [])
        delete_image_ids = validated_data.pop("delete_image_ids", [])
        precious_metal_data = validated_data.pop("precious_metal", {})
        precious_stone_data = validated_data.pop("precious_stone", {})

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if hasattr(instance, "precious_metal") and precious_metal_data:
            for attr, value in precious_metal_data.items():
                setattr(instance.precious_metal, attr, value)
            instance.precious_metal.save()

        if hasattr(instance, "precious_stone") and precious_stone_data:
            for attr, value in precious_stone_data.items():
                setattr(instance.precious_stone, attr, value)
            instance.precious_stone.save()

        instance.updated_by = request.user
        instance.save()

        if delete_image_ids:
            PreciousItemImage.objects.filter(
                id__in=delete_image_ids, precious_item=instance
            ).delete()

        if images_data:
            PreciousItemImage.objects.bulk_create(
                [
                    PreciousItemImage(precious_item=instance, image=image_url)
                    for image_url in images_data
                ]
            )

        return instance


class PreciousItemImageSerializer(ModelSerializer):
    """Serializer for the PreciousItemImage model to return image ID and URL."""

    url = SerializerMethodField()

    class Meta:
        model = PreciousItemImage
        fields = ["id", "url"]

    def get_url(self, obj):
        """Generate a pre-signed URL for the given image"""

        return get_presigned_url_from_s3(obj.image)


class PreciousStoneResponseSerializer(ModelSerializer):
    shape_cut = SerializerMethodField()

    class Meta:
        model = PreciousStone
        exclude = ["created_at", "updated_at", "precious_item"]

    def get_shape_cut(self, obj):
        return getattr(obj.shape_cut, "name", None)


class PreciousItemBaseSerializer(BusinessDetailsMixin, ModelSerializer):
    """
    Base serializer for the PreciousItem model to return a detailed response.

    This serializer includes:
    - The list of image URLs associated with the precious item.
    - Details of the related precious metal and precious stone, utilizing
      nested serializers.
    """

    material_item = MaterialItemDetailSerializer()
    precious_item_images = PreciousItemImageSerializer(source="images", many=True)
    precious_metal_details = PreciousMetalSerializer(source="precious_metal")
    precious_stone_details = PreciousStoneResponseSerializer(source="precious_stone")
    created_by = SerializerMethodField()
    carat_type = SerializerMethodField()
    business = SerializerMethodField()

    class Meta:
        model = PreciousItem
        exclude = [
            "updated_at",
            "updated_by",
            "deleted_at",
            "restored_at",
            "transaction_id",
        ]

    def get_created_by(self, obj):
        return getattr(obj.created_by, "fullname", None)

    def get_carat_type(self, obj):
        return getattr(obj.carat_type, "name", None)

    def get_business(self, obj):
        return self.serialize_business(obj, "business")


class PreciousItemResponseSerializer(PreciousItemBaseSerializer):
    """
    Extended serializer that includes additional fields while reusing
    PreciousItemBaseSerializer fields.
    """

    total_sales_count = SerializerMethodField()

    def get_total_sales_count(self, obj):
        """Get the precomputed count of completed asset purchase requests."""
        return obj.completed_asset_purchase_request_count


class BasePurchaseRequestSerializer(BusinessDetailsMixin, ModelSerializer):
    """Serializer for PurchaseRequest model."""

    precious_item = PreciousItemBaseSerializer()
    created_by = SerializerMethodField()
    business = SerializerMethodField()

    class Meta:
        model = PurchaseRequest
        fields = "__all__"
        read_only_fields = [
            "total_cost",
            "status",
            "created_by",
            "premium",
            "organization_id",
        ]

    def get_business(self, obj):
        return self.serialize_business(obj, "business")

    def get_created_by(self, obj):
        """
        Returns the creator's full name using the annotated field if available,
        else dynamically builds it from the related user instance.
        """
        creator_name = getattr(obj, "creator_full_name", None)
        if creator_name:
            return creator_name

        if hasattr(obj, "created_by") and obj.created_by:
            return obj.created_by.fullname

        return None


class PurchaseRequestResponseSerializer(BasePurchaseRequestSerializer):
    """Serializer for PurchaseRequest model."""

    # This field all sales requests for the given purchase request
    # and returns a list of all sale requests linked to this purchase request.
    # It includes the sale request ID, requested quantity, status, and created date.
    related_sale_request = SerializerMethodField()
    asset_contributions = SerializerMethodField()
    remaining_quantity = SerializerMethodField()
    remaining_weight = SerializerMethodField()
    serial_numbers = SerializerMethodField()

    def get_remaining_quantity(self, obj):
        """
        Returns remaining quantity for purchase requests.
        For sale requests, returns the remaining quantity from the related purchase request.
        """
        if obj.request_type == RequestType.SALE and obj.related_purchase_request:
            return obj.related_purchase_request.remaining_quantity
        return obj.remaining_quantity

    def get_remaining_weight(self, obj):
        """
        Returns remaining weight for purchase requests.
        For sale requests, returns the remaining weight from the related purchase request.
        """
        if obj.request_type == RequestType.SALE and obj.related_purchase_request:
            return obj.related_purchase_request.remaining_weight
        return obj.remaining_weight

    def get_related_sale_request(self, obj):
        """
        Returns a list of all sale requests linked to this purchase request.
        For purchase requests: returns all sale requests that point to this purchase request.
        For sale requests: returns all sale requests (including itself) that share the same purchase request.
        """
        if obj.request_type == RequestType.PURCHASE:
            # For purchase requests, find all sale requests linked to this purchase request
            related_sales = PurchaseRequest.objects.filter(
                request_type=RequestType.SALE, related_purchase_request=obj
            )
        elif obj.request_type == RequestType.SALE and obj.related_purchase_request:
            # For sale requests, find all sale requests (including current one) linked to the same purchase request
            related_sales = PurchaseRequest.objects.filter(
                request_type=RequestType.SALE,
                related_purchase_request=obj.related_purchase_request,
            )
        else:
            # No related purchase request, return empty list
            return []

        related_sales = related_sales.only(
            "id",
            "status",
            "requested_quantity",
            "created_at",
            "order_cost",
            "platform_fee",
            "vat",
            "taxes",
        )

        result = []
        for sale_request in related_sales:
            # Calculate investor receivable amount for all statuses
            # Investor receives: order_cost (after deduction) - platform_fee - vat - taxes
            investor_receivable_amount = (
                (sale_request.order_cost or Decimal("0.00"))
                - (sale_request.platform_fee or Decimal("0.00"))
                - (sale_request.vat or Decimal("0.00"))
                - (sale_request.taxes or Decimal("0.00"))
            )

            result.append(
                {
                    "asset_sale_request": sale_request.id,
                    "requested_quantity": sale_request.requested_quantity,
                    "order_cost": sale_request.order_cost,
                    "platform_fee": sale_request.platform_fee,
                    "vat": sale_request.vat,
                    "taxes": sale_request.taxes,
                    "investor_receivable_amount": investor_receivable_amount,
                    "associated_sale_status": sale_request.status,
                    "created_at": sale_request.created_at,
                }
            )

        return result

    def get_asset_contributions(self, obj):
        """
        Returns a list of all assets contributed to the pool or Musharakah.
        Each item includes contribution type, related pool or musharakah contract ID, quantity, and created date.
        """

        contributions = (
            AssetContribution.objects.filter(purchase_request=obj)
            .select_related("pool", "musharakah_contract_request")
            .only(
                "contribution_type",
                "quantity",
                "created_at",
                "pool__id",
                "status",
                "musharakah_contract_request__id",
                "musharakah_contract_request__musharakah_contract_status",
            )
        )

        result = []
        for contribution in contributions:
            item = {
                "contribution_type": contribution.contribution_type,
                "quantity": contribution.quantity,
                "created_at": contribution.created_at,
                "status": contribution.status,
                "used_unused_weight": contribution.used_unused_weight,
            }

            if (
                contribution.contribution_type == ContributionType.POOL
                and contribution.pool_id
            ):
                item["pool_id"] = contribution.pool_id
            elif (
                contribution.contribution_type == ContributionType.MUSHARAKAH
                and contribution.musharakah_contract_request_id
            ):
                item[
                    "musharakah_contract_request_id"
                ] = contribution.musharakah_contract_request_id
                item[
                    "musharakah_contract_status"
                ] = contribution.musharakah_contract_request.musharakah_contract_status

            result.append(item)

        return result

    def get_serial_numbers(self, obj):
        """Returns serialized precious item units for a sale request with stable ordering."""

        if obj.request_type == RequestType.SALE:
            sold_units = PreciousItemUnit.objects.filter(
                purchase_request=obj.related_purchase_request,
                sale_request=obj,
            )

            if not sold_units:
                sold_units = PreciousItemUnit.objects.filter(
                    purchase_request=obj.related_purchase_request
                )
        else:
            sold_units = PreciousItemUnit.objects.filter(purchase_request=obj)

        sold_units = sold_units.order_by("created_at", "id")

        return PreciousItemUnitResponseSerializer(sold_units, many=True).data


class PurchaseRequestDetailsSerializer(PurchaseRequestResponseSerializer):
    jewelry_product = JewelryProductResponseSerializer()


class UpdatePurchaseRequestStatusSerializer(ModelSerializer):
    status = ChoiceField(
        choices=[
            PurchaseRequestStatus.APPROVED,
            PurchaseRequestStatus.REJECTED,
        ]
    )
    serial_numbers = ListField(
        child=CharField(),
        required=False,
    )

    class Meta:
        model = PurchaseRequest
        fields = ["status", "serial_numbers"]

    def validate(self, attrs):
        purchase_request = self.instance  # The instance being updated
        business = purchase_request.business
        status = attrs.get("status")
        serial_numbers = attrs.get("serial_numbers", [])

        # For sale requests with new flow, allow PENDING_INVESTOR_CONFIRMATION status
        # For purchase requests and old sale requests, require PENDING status
        if purchase_request.request_type == RequestType.SALE:
            if purchase_request.status not in [
                PurchaseRequestStatus.PENDING,
                PurchaseRequestStatus.PENDING_INVESTOR_CONFIRMATION,
            ]:
                raise ValidationError(
                    "Sale request must be in PENDING or PENDING_INVESTOR_CONFIRMATION status."
                )
        else:
            if purchase_request.status != PurchaseRequestStatus.PENDING:
                raise ValidationError(
                    SELLER_MESSAGE["purchase_request_status_must_be_pending"]
                )

        if status == PurchaseRequestStatus.APPROVED:
            # Check if the business is suspended then not allow to approve purchase request
            if business.is_suspended:
                raise ValidationError(SELLER_MESSAGE["business_inactive"])

            # Serial number must be provided for purchase request approval
            if purchase_request.request_type == "purchase":
                if not attrs.get("serial_numbers"):
                    raise ValidationError(SELLER_MESSAGE["serial_number_required"])

            if len(serial_numbers) != int(purchase_request.requested_quantity):
                raise ValidationError(SELLER_MESSAGE["serial_number_quantity_mismatch"])

            # Check duplicates inside the same request
            if len(serial_numbers) != len(set(serial_numbers)):
                raise ValidationError(SELLER_MESSAGE["serial_number_validation"])
        return attrs


class SalesOfSelectedPeriodSerializer(Serializer):
    """
    Serializer for representing the sales data of a selected period for material items.

    Attributes:
        name (str): Material item name.
        total_sales (Decimal): Total sales for the material item.
    """

    name = CharField()
    total_sales = DecimalField(max_digits=10, decimal_places=2)


class SalesOfSelectedPeriodSerializer(Serializer):
    name = CharField()
    total_sales = DecimalField(max_digits=12, decimal_places=2)


class RoleWisePurchaseRequestCountSerializer(Serializer):
    total_purchase_requests_count = IntegerField()
    sales_requests_count = IntegerField()
    pending_purchase_requests_count = IntegerField()
    unallocated_purchase_request_count = IntegerField()
    completed_purchase_requests_count = IntegerField()
    allocated_purchase_request_count = IntegerField()


class SellerDashboardSerializer(Serializer):
    total_sales = DictField(child=DecimalField(max_digits=12, decimal_places=2))
    total_metal_quantity_sold = DecimalField(max_digits=12, decimal_places=2)
    sales_by_material = SalesOfSelectedPeriodSerializer(many=True)
    purchase_request_counts = DictField(child=RoleWisePurchaseRequestCountSerializer())


class SalesByContinentSerializer(Serializer):
    """
    Serializer for representing sales data as per nationality.

    Attributes:
        nationality (str): Nationality of the Investor.
        sales_percentage (Decimal): Sales percentage by nationality.
        material_items_sold (list): List of material items sold by the nationality.
    """

    continent = CharField()
    sales_amount = DecimalField(max_digits=12, decimal_places=2)
    sales_percentage = DecimalField(max_digits=5, decimal_places=2)
    material_items_sold = ListField(child=CharField())


class PreciousItemReportNumberSerializer(Serializer):
    """
    Serializer for checking report number of precious item.

    Attributes:
        report_number (str): The report number to validate.
    """

    report_number = CharField()


class PreciousItemUnitResponseSerializer(ModelSerializer):
    remaining_weight = DecimalField(max_digits=10, decimal_places=2, read_only=True)
    precious_item = PreciousItemBaseSerializer()

    class Meta:
        model = PreciousItemUnit
        fields = [
            "id",
            "purchase_request",
            "serial_number",
            "system_serial_number",
            "sale_request",
            "musharakah_contract",
            "pool",
            "remaining_weight",
            "precious_item",
        ]


class SaleRequestDeductionAmountSerializer(ModelSerializer):
    """Serializer for seller to set deduction amount on sale requests."""

    deduction_amount = DecimalField(
        max_digits=16, decimal_places=4, required=True, min_value=Decimal("0.00")
    )

    class Meta:
        model = PurchaseRequest
        fields = ["deduction_amount"]

    def validate(self, attrs):
        """Validate that the sale request is in the correct status."""
        sale_request = self.instance

        if sale_request.request_type != RequestType.SALE:
            raise ValidationError("This endpoint is only for sale requests.")

        if sale_request.status != PurchaseRequestStatus.PENDING_SELLER_PRICE:
            raise ValidationError(
                "Sale request must be in PENDING_SELLER_PRICE status to set deduction amount."
            )

        deduction_amount = attrs.get("deduction_amount")
        # Use initial_order_cost if available, otherwise fall back to order_cost
        initial_order_cost = (
            sale_request.initial_order_cost
            if sale_request.initial_order_cost is not None
            else sale_request.order_cost
        )

        if deduction_amount >= initial_order_cost:
            raise ValidationError(
                "Deduction amount cannot be greater than or equal to the initial order cost."
            )

        return attrs

    def update(self, instance, validated_data):
        """Update sale request with deduction amount and recalculate fees."""
        deduction_amount = validated_data["deduction_amount"]
        precious_item = instance.precious_item
        organization = instance.organization_id

        # Get initial order cost (original live price x qty x weight)
        # initial_order_cost stores the ORIGINAL price and is NEVER modified after creation
        # order_cost is the one that gets updated after deduction
        if instance.initial_order_cost is not None:
            # Use existing initial_order_cost (original price - never changes)
            initial_order_cost = instance.initial_order_cost
        else:
            # Fallback: if initial_order_cost was never set, use current order_cost
            # This should only happen for legacy records
            initial_order_cost = instance.order_cost
            # Set it once to preserve the original price
            instance.initial_order_cost = initial_order_cost

        # Calculate new order cost after deduction
        # This is the updated price that seller will pay
        new_order_cost = initial_order_cost - deduction_amount

        # Recalculate fees based on new order cost
        # Calculate platform fee
        platform_fee = calculate_platform_fee(new_order_cost, organization)

        # Calculate taxes (on platform fee for sale requests)
        taxes = platform_fee * organization.tax_rate

        # Calculate VAT
        # For 24k gold/silver, VAT is only on platform fee
        # For others, VAT is on order_cost + platform_fee
        # Import here to avoid circular import
        from investor.serializers import PurchaseRequestSerializerV2

        vat = PurchaseRequestSerializerV2.get_calculated_vat(
            PurchaseRequestSerializerV2(),
            new_order_cost,
            precious_item,
            organization,
            platform_fee,
        )

        # Calculate total cost (for seller to pay)
        total_cost = new_order_cost + platform_fee + vat + taxes

        # Update the sale request
        instance.deduction_amount = deduction_amount
        # Update order_cost with new value (after deduction)
        # Note: initial_order_cost is NOT modified - it always keeps the original price
        instance.order_cost = new_order_cost
        instance.platform_fee = platform_fee
        instance.vat = vat
        instance.taxes = taxes
        instance.total_cost = total_cost
        instance.status = PurchaseRequestStatus.PENDING_INVESTOR_CONFIRMATION
        instance.save()

        return instance
