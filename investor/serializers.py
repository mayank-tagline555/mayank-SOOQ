from decimal import ROUND_HALF_UP
from decimal import Decimal
from decimal import InvalidOperation

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Case
from django.db.models import DecimalField
from django.db.models import ExpressionWrapper
from django.db.models import F
from django.db.models import Q
from django.db.models import Sum
from django.db.models import When
from django.utils import timezone
from rest_framework import serializers
from rest_framework.serializers import CharField
from rest_framework.serializers import ChoiceField
from rest_framework.serializers import ListField
from rest_framework.serializers import ModelSerializer
from rest_framework.serializers import Serializer
from rest_framework.serializers import SerializerMethodField
from rest_framework.serializers import ValidationError

from account.message import MESSAGES as ACCOUNT_MESSAGES
from account.mixins import BusinessDetailsMixin
from account.mixins import ReceiptNumberMixin
from account.models import Organization
from account.models import OrganizationCurrency
from account.models import Transaction
from account.models import TransactionAttachment
from account.models import User
from account.models import UserAssignedBusiness
from account.models import Wallet
from account.utils import calculate_platform_fee
from investor.message import MESSAGES
from investor.models import AssetContribution
from investor.models import PreciousItemUnit
from investor.models import PurchaseRequest
from investor.utils import get_total_hold_amount_for_investor
from investor.utils import get_total_weight_of_all_asset_contributed
from investor.utils import get_total_withdrawal_pending_amount
from jeweler.models import JewelryProductMaterial
from jeweler.models import MusharakahContractRequest
from jeweler.serializers import BaseMusharakahContractRequestResponseSerializer
from jeweler.serializers import ManufacturingRequestResponseSerializer
from manufacturer.serializers import JewelryProductionDetailSerializer
from seller.message import MESSAGES as SELLER_MESSAGES
from seller.models import PreciousItem
from seller.serializers import PreciousItemBaseSerializer
from seller.serializers import PurchaseRequestResponseSerializer
from sooq_althahab.enums.account import TransactionType
from sooq_althahab.enums.account import TransferVia
from sooq_althahab.enums.account import UserRoleBusinessChoices
from sooq_althahab.enums.investor import ContributionType
from sooq_althahab.enums.investor import PurchaseRequestStatus
from sooq_althahab.enums.investor import RequestType
from sooq_althahab.enums.jeweler import MusharakahContractStatus
from sooq_althahab.enums.jeweler import RequestStatus
from sooq_althahab.enums.seller import PremiumValueType
from sooq_althahab.enums.sooq_althahab_admin import MaterialType
from sooq_althahab.enums.sooq_althahab_admin import PoolStatus
from sooq_althahab.enums.sooq_althahab_admin import Status
from sooq_althahab.enums.sooq_althahab_admin import SubscriptionPaymentTypeChoices
from sooq_althahab.payment_gateway_services.credimax.subscription.free_trial_utils import (
    validate_business_action_limits,
)
from sooq_althahab.querysets.purchase_request import get_business_from_user_token
from sooq_althahab.utils import get_presigned_url_from_s3
from sooq_althahab_admin.message import MESSAGES as ADMIN_MESSAGES
from sooq_althahab_admin.models import MetalPriceHistory
from sooq_althahab_admin.models import Pool
from sooq_althahab_admin.models import PoolContribution
from sooq_althahab_admin.serializers import BusinessSubscriptionPlanSerializer
from sooq_althahab_admin.serializers import PoolResponseSerializer

from .utils import create_manual_contributions


class BasePaymentSessionSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=10, decimal_places=4, min_value=Decimal("1")
    )
    fee_rate = None

    def validate_amount(self, value):
        try:
            base_amount = value
            # Calculate total charged amount to cover the fee and still get base_amount
            total = (base_amount / (Decimal("1.0") - self.fee_rate)).quantize(
                Decimal("0.001"), rounding=ROUND_HALF_UP
            )
            fee = (total - base_amount).quantize(
                Decimal("0.001"), rounding=ROUND_HALF_UP
            )

            self.base_amount = base_amount
            self.fee = fee
            self.total_amount = total
        except (InvalidOperation, ValueError, ZeroDivisionError):
            raise serializers.ValidationError("Invalid amount value.")
        return value

    def get_base_amount(self):
        return getattr(self, "base_amount", Decimal("0"))

    def get_fee(self):
        return getattr(self, "fee", Decimal("0"))

    def get_total_amount(self):
        return getattr(self, "total_amount", Decimal("0"))


class CreateCredimaxPaymentSessionSerializer(BasePaymentSessionSerializer):
    fee_rate = Decimal(settings.CREDIMAX_ADDITIONAL_FEE_RATE)


class CreateBenefitPaymentSessionSerializer(BasePaymentSessionSerializer):
    fee_rate = Decimal(settings.BENEFIT_ADDITIONAL_FEE_RATE)


class PurchaseRequestSerializer(ModelSerializer):
    """Serializer for PurchaseRequest model."""

    precious_item = serializers.PrimaryKeyRelatedField(
        queryset=PreciousItem.objects.all(),
        error_messages={
            "does_not_exist": SELLER_MESSAGES["precious_item_not_found"],
            "null": MESSAGES["precious_item_required"],
        },
    )

    class Meta:
        model = PurchaseRequest
        exclude = [
            "updated_by",
            "updated_at",
            "related_purchase_request",
        ]
        read_only_fields = [
            "business",
            "total_cost",
            "status",
            "created_by",
            "action_by",
            "premium",
            "organization_id",
            "completed_at",
            "vat",
            "taxes",
            "platform_fee",
            "order_cost",
        ]

    def validate(self, attrs):
        request = self.context.get("request")
        organization_code = request.auth.get("organization_code")

        try:
            Organization.objects.get(code=organization_code)
        except:
            raise serializers.ValidationError(MESSAGES["organization_not_found"])

        return attrs

    def create(self, validated_data):
        """
        Override create method to calculate the total cost based on material type and premium pricing.

        The calculation for purchase request:
        Determines the order cost:
            - For METAL: order cost is calculated as requested quantity with price locked(live price).
            - For STONE: order cost is fetched from the associated precious stone price.
        Applies the premium price based on its type:
            - If it's a percentage-based premium, calculates it as a percentage of the order cost.
            - If it's a fixed amount, applies the fixed amount directly.
            - If both (percentage + fixed amount) are applicable, adds the fixed amount first and then calculates the percentage premium.
        Calculates additional costs: platform fee, VAT, and taxes based on the organization's settings.
        total_order_cost: This represents the total payable amount for the purchase request.
        """
        with transaction.atomic():
            precious_item = validated_data.get("precious_item")

            # Check if the precious item is enabled
            if not precious_item.is_enabled:
                raise serializers.ValidationError(
                    MESSAGES["precious_item_out_of_stock"]
                )

            requested_quantity = validated_data.get("requested_quantity")
            premium_price_rate = precious_item.premium_price_rate
            premium_value_type = precious_item.premium_value_type
            request = self.context.get("request")
            organization_code = request.auth.get("organization_code")

            # Fetch Organization
            organization = Organization.objects.get(code=organization_code)

            if precious_item.material_type == MaterialType.METAL:
                price_locked = self.get_live_metal_price(precious_item)
                precious_metal_weight = precious_item.precious_metal.weight
                order_cost = (requested_quantity * precious_metal_weight) * price_locked
            else:  # MaterialType.STONE
                precious_item.is_enabled = False
                precious_item.save()
                price_locked = order_cost = precious_item.precious_stone.price

            # Calculated the premium price based on its type percentage or amount or both
            if premium_value_type == PremiumValueType.PERCENTAGE:
                premium_price = order_cost * premium_price_rate
            elif premium_value_type == PremiumValueType.AMOUNT:
                # Calculate premium price as a fixed amount based on the requested quantity.
                premium_price = precious_item.premium_price_amount * requested_quantity
            elif premium_value_type == PremiumValueType.BOTH:
                premium_price_amount = (
                    precious_item.premium_price_amount * requested_quantity
                )
                premium_price = (order_cost * premium_price_rate) + premium_price_amount

            # Calculate the final price with premium included
            price_with_premium = order_cost + premium_price

            # Calculate the platform fee based on its type (percentage or fixed amount)
            platform_fee = calculate_platform_fee(price_with_premium, organization)
            vat = price_with_premium * organization.vat_rate
            taxes = price_with_premium * organization.tax_rate

            # Calculate the total cost for asset purchase request with adding vat, platform, taxes
            total_order_cost = price_with_premium + platform_fee + vat + taxes

            # Retrieve all users who are assigned to this business
            business = get_business_from_user_token(request, "business")
            if not business:
                raise serializers.ValidationError(
                    MESSAGES["business_account_not_found"]
                )

            # Get the wallet balance of the business
            wallet = Wallet.objects.get(business=business)

            # Get the total hold amount of all pending purchase request
            total_hold_amount_for_purchase_request = get_total_hold_amount_for_investor(
                business
            )

            # Total pending withdrawals for business
            total_withdrawal_pending_amount = get_total_withdrawal_pending_amount(
                business
            )

            # Ensure the wallet balance is sufficient to cover the new purchase request
            if (
                wallet.balance
                - total_hold_amount_for_purchase_request
                - total_withdrawal_pending_amount
            ) < total_order_cost:
                raise serializers.ValidationError(MESSAGES["insufficient_balance"])

            # Update validated data with calculated fields
            validated_data.update(
                {
                    "business": business,
                    "order_cost": order_cost,
                    "vat": vat,
                    "taxes": taxes,
                    "platform_fee": platform_fee,
                    "premium": premium_price,
                    "total_cost": total_order_cost,
                    "price_locked": price_locked,
                }
            )
            return PurchaseRequest.objects.create(**validated_data)

    def get_live_metal_price(self, precious_item):
        """Calculate the latest live metal price for a given precious item."""
        latest_metal_price = (
            MetalPriceHistory.objects.filter(
                global_metal=precious_item.material_item.global_metal
            )
            .order_by("global_metal", "-created_at")
            .first()
        )
        carat_number = int(precious_item.carat_type.name.rstrip("k"))
        price = (carat_number * latest_metal_price.price) / 24
        currency_rate = OrganizationCurrency.objects.filter(is_default=True).first()
        metal_price = Decimal(price) * currency_rate.rate
        return round(metal_price, 2)


class PurchaseRequestSerializerV2(ModelSerializer):
    """Serializer for PurchaseRequest model."""

    precious_item = serializers.PrimaryKeyRelatedField(
        queryset=PreciousItem.objects.all(),
        error_messages={
            "does_not_exist": SELLER_MESSAGES["precious_item_not_found"],
            "null": MESSAGES["precious_item_required"],
        },
    )

    class Meta:
        model = PurchaseRequest
        exclude = [
            "updated_by",
            "updated_at",
            "related_purchase_request",
        ]
        read_only_fields = [
            "business",
            "total_cost",
            "status",
            "created_by",
            "action_by",
            "premium",
            "organization_id",
            "completed_at",
            "vat",
            "taxes",
            "platform_fee",
            "order_cost",
        ]

    def validate(self, attrs):
        request = self.context.get("request")
        organization_code = request.auth.get("organization_code")

        try:
            Organization.objects.get(code=organization_code)
        except:
            raise serializers.ValidationError(MESSAGES["organization_not_found"])

        return attrs

    def create(self, validated_data):
        """
        Override create method to calculate the total cost based on material type and premium pricing.

        The calculation for purchase request:
        Determines the order cost:
            - For METAL: order cost is calculated as requested quantity with price locked(live price).
            - For STONE: order cost is fetched from the associated precious stone price.
        Applies the premium price based on its type:
            - If it's a percentage-based premium, calculates it as a percentage of the order cost.
            - If it's a fixed amount, applies the fixed amount directly.
            - If both (percentage + fixed amount) are applicable, adds the fixed amount first and then calculates the percentage premium.
        Calculates additional costs: platform fee, VAT, and taxes based on the organization's settings.
        total_order_cost: This represents the total payable amount for the purchase request.
        """
        with transaction.atomic():
            precious_item = validated_data.get("precious_item")

            # Check if the precious item is enabled
            if not precious_item.is_enabled:
                raise serializers.ValidationError(
                    MESSAGES["precious_item_out_of_stock"]
                )

            requested_quantity = validated_data.get("requested_quantity")
            premium_price_rate = precious_item.premium_price_rate
            premium_value_type = precious_item.premium_value_type
            request = self.context.get("request")
            organization_code = request.auth.get("organization_code")

            # Fetch Organization
            organization = Organization.objects.get(code=organization_code)

            if precious_item.material_type == MaterialType.METAL:
                price_locked = self.get_live_metal_price(precious_item)
                precious_metal_weight = precious_item.precious_metal.weight
                order_cost = (requested_quantity * precious_metal_weight) * price_locked
            else:  # MaterialType.STONE
                precious_item.is_enabled = False
                precious_item.save(update_fields=["is_enabled"])
                price_locked = order_cost = precious_item.precious_stone.price

            # Calculated the premium price based on its type percentage or amount or both
            if premium_value_type == PremiumValueType.PERCENTAGE:
                premium_price = order_cost * premium_price_rate
            elif premium_value_type == PremiumValueType.AMOUNT:
                # Calculate premium price as a fixed amount based on the requested quantity.
                premium_price = precious_item.premium_price_amount * requested_quantity
            elif premium_value_type == PremiumValueType.BOTH:
                premium_price_amount = (
                    precious_item.premium_price_amount * requested_quantity
                )
                premium_price = (order_cost * premium_price_rate) + premium_price_amount
            # Calculate the final price with premium included
            price_with_premium = order_cost + premium_price

            # Calculate the platform fee based on its type (percentage or fixed amount)
            platform_fee = calculate_platform_fee(price_with_premium, organization)
            taxes = price_with_premium * organization.tax_rate

            # Retrieve all users who are assigned to this business
            business = get_business_from_user_token(request, "business")
            if not business:
                raise serializers.ValidationError(
                    MESSAGES["business_account_not_found"]
                )

            # Validate metal purchase weight limit for JEWELER users only
            if (
                business.business_account_type == UserRoleBusinessChoices.JEWELER
                and precious_item.material_type == MaterialType.METAL
            ):
                # Calculate total purchase weight
                precious_metal_weight = precious_item.precious_metal.weight
                purchase_weight = requested_quantity * precious_metal_weight

                # Validate against subscription plan limits
                try:
                    validate_business_action_limits(
                        business, "metal_purchase", weight=purchase_weight
                    )
                except DjangoValidationError as ve:
                    # FreeTrialLimitationError extends Django's ValidationError
                    # Django ValidationError stores messages as a list
                    # Access the first message from the messages property
                    error_msg = ve.messages[0] if ve.messages else str(ve)
                    raise serializers.ValidationError(error_msg)

            business_subscription_plan = business.business_subscription_plan.order_by(
                "-created_at"
            ).first()
            if not business_subscription_plan:
                raise serializers.ValidationError(
                    "No subscription plan found for this business."
                )

            # Get pro-rata rate from subscription plan
            pro_rata_rate = business_subscription_plan.pro_rata_rate
            validated_data["pro_rata_rate"] = pro_rata_rate
            # Calculate pro-rata fee
            validated_data["pro_rata_fee"] = (
                price_with_premium * pro_rata_rate / 12 * (13 - timezone.now().month)
            )

            # Default pro-rata value is the calculated fee
            pro_rata_value = validated_data["pro_rata_fee"]

            # Calculate VAT including pro-rata fee by default
            vat = self.get_calculated_vat(
                price_with_premium,
                precious_item,
                organization,
                platform_fee,
                pro_rata_value,
            )

            # Handle payment type logic
            if (
                business_subscription_plan.payment_type
                == SubscriptionPaymentTypeChoices.PREPAID
            ):
                # For prepaid subscriptions, charge the pro-rata fee immediately
                validated_data["pro_rata_mode"] = SubscriptionPaymentTypeChoices.PREPAID
                pro_rata_value = validated_data["pro_rata_fee"]

            else:
                # For postpaid subscriptions, defer pro-rata fee to future billing
                validated_data[
                    "pro_rata_mode"
                ] = SubscriptionPaymentTypeChoices.POSTPAID
                pro_rata_value = 0
                # Calculate annual pro-rata fee
                validated_data["annual_pro_rata_fee"] = (
                    price_with_premium * pro_rata_rate / 12 * (13 - 1)
                )
                # Do NOT add pro-rata fee to total order cost in postpaid mode

            # Calculate the total cost for asset purchase request with adding vat, platform, taxes
            total_order_cost = (
                price_with_premium + pro_rata_value + platform_fee + vat + taxes
            )

            # Get the wallet balance of the business
            wallet = Wallet.objects.get(business=business)

            # Get the total hold amount of all pending purchase request
            total_hold_amount_for_purchase_request = get_total_hold_amount_for_investor(
                business
            )

            # Total pending withdrawals for business
            total_withdrawal_pending_amount = get_total_withdrawal_pending_amount(
                business
            )

            # Ensure the wallet balance is sufficient to cover the new purchase request
            if (
                wallet.balance
                - total_hold_amount_for_purchase_request
                - total_withdrawal_pending_amount
            ) < total_order_cost:
                raise serializers.ValidationError(MESSAGES["insufficient_balance"])

            # Update validated data with calculated fields
            validated_data.update(
                {
                    "business": business,
                    "order_cost": order_cost,
                    "vat": vat,
                    "taxes": taxes,
                    "platform_fee": platform_fee,
                    "premium": premium_price,
                    "total_cost": total_order_cost,
                    "price_locked": price_locked,
                }
            )
            return PurchaseRequest.objects.create(**validated_data)

    def get_live_metal_price(self, precious_item):
        """Calculate the latest live metal price for a given precious item."""
        latest_metal_price = (
            MetalPriceHistory.objects.filter(
                global_metal=precious_item.material_item.global_metal
            )
            .order_by("global_metal", "-created_at")
            .first()
        )
        carat_number = int(precious_item.carat_type.name.rstrip("k"))
        price = (carat_number * latest_metal_price.price) / 24
        currency_rate = OrganizationCurrency.objects.filter(is_default=True).first()
        metal_price = Decimal(price) * currency_rate.rate
        return round(metal_price, 2)

    def get_calculated_vat(
        self, base_amount, precious_item, organization, platform_fee, pro_rata_value=0
    ):
        # Determine VAT calculation based on material type, item, and carat.
        # - If the precious item is a METAL and specifically Gold or Silver with 24k purity,
        #   then VAT is calculated on the platform fee.
        # - Otherwise, VAT is calculated on the price with premium.
        is_24k_gold_or_silver = (
            precious_item.material_type == MaterialType.METAL
            and precious_item.material_item.name in {"Gold", "Silver"}
            and precious_item.carat_type.name == "24k"
        )

        if is_24k_gold_or_silver:
            vat_base = platform_fee + pro_rata_value
        else:
            vat_base = base_amount + platform_fee + pro_rata_value

        return round(vat_base * organization.vat_rate, 4)


class AdminPreciousItemUnitSerializer(ModelSerializer):
    """Serializer for PreciousItemUnit model with detailed information."""

    remaining_weight = serializers.DecimalField(
        max_digits=10, decimal_places=3, read_only=True
    )

    class Meta:
        model = PreciousItemUnit
        fields = [
            "id",
            "serial_number",
            "system_serial_number",
            "remaining_weight",
        ]


class AdminPurchaseRequestSerializer(ModelSerializer):
    """Serializer for PurchaseRequest model."""

    precious_item = serializers.PrimaryKeyRelatedField(
        queryset=PreciousItem.objects.all(),
        required=True,
        error_messages={
            "does_not_exist": SELLER_MESSAGES["precious_item_not_found"],
            "null": MESSAGES["precious_item_required"],
            "required": MESSAGES["precious_item_required"],
        },
    )
    investor_id = serializers.CharField(write_only=True, required=True)
    requested_quantity = serializers.IntegerField(required=True)
    price_locked = serializers.DecimalField(
        max_digits=16, decimal_places=4, required=True
    )
    precious_item_units = AdminPreciousItemUnitSerializer(many=True, required=False)

    class Meta:
        model = PurchaseRequest
        exclude = [
            "updated_by",
            "updated_at",
            "related_purchase_request",
            "deleted_at",
            "restored_at",
            "transaction_id",
        ]
        read_only_fields = [
            "business",
            "total_cost",
            "status",
            "created_by",
            "action_by",
            "premium",
            "organization_id",
            "completed_at",
            "vat",
            "taxes",
            "platform_fee",
            "order_cost",
        ]

    def validate(self, attrs):
        request = self.context.get("request")
        organization_code = request.auth.get("organization_code")
        precious_item_units = attrs.get("precious_item_units", [])
        requested_quantity = attrs.get("requested_quantity")

        if not Organization.objects.filter(code=organization_code).exists():
            raise serializers.ValidationError(MESSAGES["organization_not_found"])

        # Check investor exists
        investor_id = attrs.get("investor_id")
        if not User.objects.filter(id=investor_id).exists():
            raise serializers.ValidationError(MESSAGES["investor_not_found"])

        if len(precious_item_units) != int(requested_quantity):
            raise ValidationError(SELLER_MESSAGES["serial_number_quantity_mismatch"])

        return attrs

    def create(self, validated_data):
        with transaction.atomic():
            precious_item = validated_data.get("precious_item")
            investor_id = validated_data.pop("investor_id")
            precious_item_units = validated_data.pop("precious_item_units", [])
            investor = User.objects.get(id=investor_id)

            # Check if the precious item is enabled
            if not precious_item.is_enabled:
                raise serializers.ValidationError(
                    MESSAGES["precious_item_out_of_stock"]
                )

            requested_quantity = validated_data.get("requested_quantity")

            # Get investor’s business
            user_business = UserAssignedBusiness.global_objects.filter(
                user=investor
            ).first()
            if not user_business or not user_business.business:
                raise serializers.ValidationError(
                    MESSAGES["business_account_not_found"]
                )
            business = user_business.business

            business_subscription_plan = business.business_subscription_plan.order_by(
                "-created_at"
            ).first()
            if not business_subscription_plan:
                raise serializers.ValidationError(
                    "No subscription plan found for this business."
                )

            # Pricing & calculations
            premium_price_rate = precious_item.premium_price_rate
            premium_value_type = precious_item.premium_value_type
            request = self.context.get("request")
            organization_code = request.auth.get("organization_code")
            organization = Organization.objects.get(code=organization_code)

            if precious_item.material_type == MaterialType.METAL:
                price_locked = validated_data.get("price_locked")
                precious_metal_weight = precious_item.precious_metal.weight
                order_cost = (requested_quantity * precious_metal_weight) * price_locked
            else:  # STONE
                precious_item.is_enabled = False
                precious_item.save(update_fields=["is_enabled"])
                price_locked = order_cost = precious_item.precious_stone.price

            # Premium calculation
            if premium_value_type == PremiumValueType.PERCENTAGE:
                premium_price = order_cost * premium_price_rate
            elif premium_value_type == PremiumValueType.AMOUNT:
                premium_price = precious_item.premium_price_amount * requested_quantity
            elif premium_value_type == PremiumValueType.BOTH:
                premium_price_amount = (
                    precious_item.premium_price_amount * requested_quantity
                )
                premium_price = (order_cost * premium_price_rate) + premium_price_amount
            else:
                premium_price = 0

            price_with_premium = order_cost + premium_price
            platform_fee = calculate_platform_fee(price_with_premium, organization)
            taxes = price_with_premium * organization.tax_rate

            pro_rata_rate = business_subscription_plan.pro_rata_rate
            validated_data["pro_rata_rate"] = pro_rata_rate
            # Calculate pro-rata fee
            validated_data["pro_rata_fee"] = (
                price_with_premium * pro_rata_rate / 12 * (13 - timezone.now().month)
            )

            # Default pro-rata value is the calculated fee
            pro_rata_value = validated_data["pro_rata_fee"]

            # Calculate VAT including pro-rata fee by default
            vat = PurchaseRequestSerializerV2.get_calculated_vat(
                self,
                order_cost,
                precious_item,
                organization,
                platform_fee,
                pro_rata_value,
            )

            # Handle payment type logic
            if (
                business_subscription_plan.payment_type
                == SubscriptionPaymentTypeChoices.PREPAID
            ):
                # For prepaid subscriptions, charge the pro-rata fee immediately
                validated_data["pro_rata_mode"] = SubscriptionPaymentTypeChoices.PREPAID
                pro_rata_value = validated_data["pro_rata_fee"]

            else:
                # For postpaid subscriptions, defer pro-rata fee to future billing
                validated_data[
                    "pro_rata_mode"
                ] = SubscriptionPaymentTypeChoices.POSTPAID
                pro_rata_value = 0
                # Calculate annual pro-rata fee
                validated_data["annual_pro_rata_fee"] = (
                    price_with_premium * pro_rata_rate / 12 * (13 - 1)
                )
                # Do NOT add pro-rata fee to total order cost in postpaid mode

            total_order_cost = (
                price_with_premium + pro_rata_value + platform_fee + vat + taxes
            )
            # Genrate invoice number
            mixin = ReceiptNumberMixin()
            invoice_number = mixin.generate_receipt_number(
                users_business=business,
                model_cls=PurchaseRequest,
            )

            validated_data.update(
                {
                    "business": business,
                    "order_cost": order_cost,
                    "vat": vat,
                    "taxes": taxes,
                    "platform_fee": platform_fee,
                    "premium": premium_price,
                    "total_cost": total_order_cost,
                    "price_locked": price_locked,
                    "organization_id": organization,
                    "status": PurchaseRequestStatus.COMPLETED,
                    "completed_at": timezone.now(),
                    "action_by": self.context["request"].user,
                    "created_by": self.context["request"].user,
                    "invoice_number": invoice_number,
                }
            )
            purchase_request = PurchaseRequest.objects.create(**validated_data)

            # Handle precious item units if provided
            if precious_item_units:
                units_to_create = []
                serial_numbers_to_check = []
                system_serial_numbers_to_check = []

                # Collect all serial numbers for validation
                for unit_data in precious_item_units:
                    serial_number = unit_data.get("serial_number")
                    system_serial_number = unit_data.get("system_serial_number")
                    if serial_number and system_serial_number:
                        serial_numbers_to_check.append(serial_number)
                        system_serial_numbers_to_check.append(system_serial_number)

                # Single optimized query to check for existing serial numbers
                if serial_numbers_to_check or system_serial_numbers_to_check:
                    # Convert to sets for faster lookup
                    serial_numbers_set = set(serial_numbers_to_check)
                    system_serial_numbers_set = set(system_serial_numbers_to_check)

                    if len(serial_numbers_to_check) != len(serial_numbers_set):
                        raise ValidationError(
                            SELLER_MESSAGES["serial_number_validation"]
                        )

                    if len(system_serial_numbers_to_check) != len(
                        system_serial_numbers_set
                    ):
                        raise ValidationError(
                            ADMIN_MESSAGES["system_serial_number_validation"]
                        )

                    # Build query conditions
                    query_conditions = Q()
                    if serial_numbers_to_check:
                        query_conditions |= Q(serial_number__in=serial_numbers_to_check)
                    if system_serial_numbers_to_check:
                        query_conditions |= Q(
                            system_serial_number__in=system_serial_numbers_to_check
                        )

                    # Single query to get all existing serial numbers
                    existing_units = PreciousItemUnit.objects.filter(
                        query_conditions
                    ).values("serial_number", "system_serial_number")

                    # Check for duplicates and collect error messages
                    duplicate_serial_numbers = []
                    duplicate_system_serial_numbers = []

                    for unit in existing_units:
                        if unit["serial_number"] in serial_numbers_set:
                            duplicate_serial_numbers.append(unit["serial_number"])
                        if unit["system_serial_number"] in system_serial_numbers_set:
                            duplicate_system_serial_numbers.append(
                                unit["system_serial_number"]
                            )

                    # Raise validation error if duplicates found
                    error_messages = []
                    if duplicate_serial_numbers:
                        error_messages.append(
                            MESSAGES["serial_number_already_exist"].format(
                                serial_numbers=", ".join(duplicate_serial_numbers)
                            )
                        )
                    if duplicate_system_serial_numbers:
                        error_messages.append(
                            MESSAGES["system_serial_number_already_exist"].format(
                                system_serial_numbers=", ".join(
                                    duplicate_system_serial_numbers
                                )
                            )
                        )

                    if error_messages:
                        raise ValidationError("; ".join(error_messages))

                # Create units if no duplicates found
                for unit_data in precious_item_units:
                    serial_number = unit_data.get("serial_number")
                    system_serial_number = unit_data.get("system_serial_number")
                    if serial_number and system_serial_number:
                        units_to_create.append(
                            PreciousItemUnit(
                                purchase_request=purchase_request,
                                precious_item=precious_item,
                                serial_number=serial_number,
                                system_serial_number=system_serial_number,
                            )
                        )
                if units_to_create:
                    PreciousItemUnit.objects.bulk_create(units_to_create)

            # Always return instance
            return purchase_request


class SaleRequestSerializer(Serializer):
    """Serializer for creating asset sale requests."""

    purchase_request_id = serializers.CharField(required=True)
    requested_quantity = serializers.DecimalField(
        max_digits=10, decimal_places=4, required=True
    )

    def validate(self, attrs):
        """Validate the sale request creation against a valid purchase request."""

        purchase_request = PurchaseRequest.global_objects.filter(
            id=attrs.get("purchase_request_id")
        ).first()

        if not purchase_request:
            raise ValidationError(MESSAGES["purchase_request_not_found"])

        if (
            purchase_request.precious_item.business.deleted_at
            or purchase_request.precious_item.business.is_suspended
        ):
            raise ValidationError(MESSAGES["seller_business_inactive_for_sale_request"])

        if purchase_request.status not in {
            PurchaseRequestStatus.APPROVED,
            PurchaseRequestStatus.COMPLETED,
        }:
            raise ValidationError(MESSAGES["purchase_request_not_eligible_for_sale"])

        # Quantity validation
        requested_quantity = attrs.get("requested_quantity")
        remaining_qty = purchase_request.remaining_quantity

        if requested_quantity <= 0:
            raise ValidationError(MESSAGES["invalid_requested_quantity"])

        if remaining_qty <= 0:
            raise ValidationError(MESSAGES["purchase_request_item_already_sold"])

        if requested_quantity > remaining_qty:
            raise ValidationError(
                MESSAGES["exceeds_available_quantity"].format(quantity=remaining_qty)
            )

        attrs.update(
            {
                "precious_item": purchase_request.precious_item,
                "purchase_request": purchase_request,
            }
        )

        return attrs

    # TODO: Manage all calculations in single file for all
    def calculate_fees(self, order_cost, organization, precious_item):
        """Calculate platform fee, VAT, and taxes."""

        # Calculate the platform fee based on its type (percentage or fixed amount)
        platform_fee = calculate_platform_fee(order_cost, organization)
        taxes = platform_fee * organization.tax_rate
        vat = PurchaseRequestSerializerV2.get_calculated_vat(
            self, order_cost, precious_item, organization, platform_fee
        )
        total_order_cost = order_cost + platform_fee + vat + taxes
        return platform_fee, vat, taxes, total_order_cost

    def create(self, validated_data):
        """Handle asset sale request creation logic."""
        request = self.context["request"]
        user = request.user
        organization_code = request.auth.get("organization_code")

        precious_item = validated_data["precious_item"]
        requested_quantity = validated_data["requested_quantity"]
        purchase_request = validated_data["purchase_request"]

        # TODO: Manage all calculations in single file for all
        if precious_item.material_type == MaterialType.METAL:
            # Create a temporary instance to call the method
            temp_serializer = PurchaseRequestSerializer()
            price_locked = temp_serializer.get_live_metal_price(precious_item)
            precious_metal_weight = precious_item.precious_metal.weight
            order_cost = (requested_quantity * precious_metal_weight) * price_locked
        else:  # MaterialType.STONE
            price_locked = order_cost = precious_item.precious_stone.price

        organization = Organization.objects.get(code=organization_code)

        # For new sales flow: Calculate initial order_cost (live price x qty x weight)
        # but don't calculate fees yet - seller will set deduction_amount first
        # Store initial order_cost in initial_order_cost field for reference
        # Store it also in order_cost initially (will be updated after seller sets deduction)
        # Status is set to PENDING_SELLER_PRICE - seller needs to add deduction_amount

        # Create the sale request with initial status PENDING_SELLER_PRICE
        # Fees will be recalculated after seller sets deduction_amount
        sale_request = PurchaseRequest.objects.create(
            business=purchase_request.business,
            precious_item=precious_item,
            requested_quantity=requested_quantity,
            price_locked=price_locked,
            organization_id=organization,
            initial_order_cost=order_cost,  # Store original order cost (live price calculation)
            order_cost=order_cost,  # Initially same as initial_order_cost, will be updated after deduction
            # Below values will be recalculated after seller sets deduction
            total_cost=Decimal("0.00"),
            platform_fee=Decimal("0.00"),
            vat=Decimal("0.00"),
            taxes=Decimal("0.00"),
            deduction_amount=Decimal("0.00"),  # Seller will set this
            status=PurchaseRequestStatus.PENDING_SELLER_PRICE,
            request_type=RequestType.SALE,
            created_by=user,
            related_purchase_request=purchase_request,
        )

        return sale_request


class SaleRequestConfirmationSerializer(Serializer):
    """Serializer for investor to approve/reject sale requests with proposed price."""

    status = ChoiceField(
        choices=[
            PurchaseRequestStatus.APPROVED,
            PurchaseRequestStatus.REJECTED,
        ],
        required=True,
    )

    def validate(self, attrs):
        """Validate that the sale request is in the correct status."""
        sale_request = self.context.get("sale_request")

        if not sale_request:
            raise ValidationError("Sale request not found.")

        if sale_request.request_type != RequestType.SALE:
            raise ValidationError("This endpoint is only for sale requests.")

        if sale_request.status != PurchaseRequestStatus.PENDING_INVESTOR_CONFIRMATION:
            raise ValidationError(
                "Sale request must be in PENDING_INVESTOR_CONFIRMATION status to confirm."
            )

        return attrs


class TransactionAttachmentSerializer(ModelSerializer):
    """Serializer for TransactionAttachment model."""

    attachment = serializers.SerializerMethodField()

    class Meta:
        model = TransactionAttachment
        fields = ["id", "attachment"]

    def get_attachment(self, obj):
        """Generate a presigned URL for the attachment field in the model using the PresignedUrlSerializer."""
        object_name = obj.attachment
        return get_presigned_url_from_s3(object_name)


class TransactionResponseSerializer(BusinessDetailsMixin, ModelSerializer):
    purchase_request = PurchaseRequestResponseSerializer()
    from_business = serializers.SerializerMethodField()
    to_business = serializers.SerializerMethodField()
    attachments = TransactionAttachmentSerializer(
        source="transaction_attachments", many=True, required=False
    )
    transaction_source_type = serializers.CharField(read_only=True)

    class Meta:
        model = Transaction
        exclude = [
            "transaction_id",
            "deleted_at",
            "restored_at",
            "benefit_payment_id",
            "benefit_result",
            "benefit_response",
            "log_details",
        ]

    def get_from_business(self, obj):
        return self.serialize_business(obj, "from_business")

    def get_to_business(self, obj):
        return self.serialize_business(obj, "to_business")


class TransactionDetailResponseSerializer(BusinessDetailsMixin, ModelSerializer):
    from_business = serializers.SerializerMethodField()
    to_business = serializers.SerializerMethodField()
    attachments = TransactionAttachmentSerializer(
        source="transaction_attachments", many=True, required=False
    )
    transaction_source_type = serializers.CharField(read_only=True)
    purchase_request = PurchaseRequestResponseSerializer()
    business_subscription = BusinessSubscriptionPlanSerializer()
    manufacturing_request = ManufacturingRequestResponseSerializer()
    jewelry_production = JewelryProductionDetailSerializer()

    class Meta:
        model = Transaction
        exclude = [
            "transaction_id",
            "deleted_at",
            "restored_at",
            "benefit_payment_id",
            "benefit_result",
            "benefit_response",
            "log_details",
        ]

    def get_from_business(self, obj):
        return self.serialize_business(obj, "from_business")

    def get_to_business(self, obj):
        return self.serialize_business(obj, "to_business")


class DepositTransactionSerializer(ModelSerializer):
    """Serializer for wallet transactions (deposit/withdrawal)."""

    attachments = ListField(child=CharField(), required=False)

    class Meta:
        model = Transaction
        fields = ["amount", "notes", "attachments"]

    def validate(self, data):
        """Validates transaction data including positive amount and wallet balance limits."""
        request = self.context["request"]
        attachments = request.data.get("attachments", [])
        if not attachments:
            raise ValidationError(MESSAGES["attachments_required"])

        # Fetch business and wallet
        business = get_business_from_user_token(request, "business")
        if not business:
            raise ValidationError(MESSAGES["business_account_not_found"])

        return data

    def create(self, validated_data):
        """Create a wallet transaction and update wallet balance."""
        request = self.context["request"]
        attachments = validated_data.pop("attachments", [])
        organization = request.auth.get("organization_code")

        try:
            organization = Organization.objects.get(code=organization)
            organization_currency = OrganizationCurrency.objects.filter(
                organization=organization, is_default=True
            ).first()
        except:
            raise ValidationError(ACCOUNT_MESSAGES["organization_not_found"])

        business = get_business_from_user_token(request, "business")

        if request.user.user_preference.organization_currency:
            validated_data[
                "currency"
            ] = request.user.user_preference.organization_currency.currency_code
        else:
            validated_data["currency"] = organization_currency.currency_code

        validated_data["transfer_via"] = TransferVia.ORGANIZATION_ADMIN
        validated_data["transaction_type"] = TransactionType.DEPOSIT

        with transaction.atomic():
            deposit_transaction = Transaction.objects.create(
                from_business=business,
                to_business=business,
                created_by=request.user,
                **validated_data,
            )

            if attachments:
                TransactionAttachment.objects.bulk_create(
                    [
                        TransactionAttachment(
                            transaction=deposit_transaction, attachment=attachment_url
                        )
                        for attachment_url in attachments
                    ]
                )

        return deposit_transaction


class WithdrawTransactionSerializer(ModelSerializer):
    """Serializer for wallet transactions (deposit/withdrawal)."""

    class Meta:
        model = Transaction
        fields = ["amount"]

    def validate(self, data):
        """Validates transaction data including positive amount and wallet balance limits."""
        request = self.context["request"]
        amount = data["amount"]

        # Fetch business, wallet and user's within the logged-in user's business.
        business = get_business_from_user_token(request, "business")
        if not business:
            raise ValidationError(MESSAGES["business_account_not_found"])

        try:
            wallet = Wallet.objects.get(business=business)
        except:
            raise ValidationError(MESSAGES["wallet_not_found"])

        # Total pending withdrawals for business
        total_withdrawal_pending_amount = get_total_withdrawal_pending_amount(business)

        if wallet.business.business_account_type == UserRoleBusinessChoices.INVESTOR:
            # Check if the wallet balance is sufficient to cover the hold amount and the withdrawal amount
            total_hold_amount_for_investor = get_total_hold_amount_for_investor(
                business
            )

            if (
                wallet.balance
                - total_hold_amount_for_investor
                - total_withdrawal_pending_amount
            ) < amount:
                raise ValidationError(MESSAGES["insufficient_balance"])

        elif (wallet.balance - total_withdrawal_pending_amount) < amount:
            raise ValidationError(MESSAGES["insufficient_balance"])

        # Set this request for organization admin to process the withdrawal request.
        data["transfer_via"] = TransferVia.ORGANIZATION_ADMIN

        return data

    def create(self, validated_data):
        """Create a wallet transaction and update wallet balance."""
        request = self.context["request"]
        # NOTE: Enable when we support multi-currency payments.
        # currency = request.user.user_preference.organization_currency
        business = get_business_from_user_token(request, "business")
        if not business:
            raise ValidationError(MESSAGES["business_account_not_found"])

        validated_data["transaction_type"] = TransactionType.WITHDRAWAL
        # validated_data["currency"] = currency

        # Create and return the transaction record
        return Transaction.objects.create(
            from_business=business,
            to_business=business,
            created_by=request.user,
            **validated_data,
        )


class PurchaseRequestContributionSerializer(ModelSerializer):
    """Serializer for Purchase Request to handle asset contributions only for jeweler."""

    precious_item = PreciousItemBaseSerializer()
    asset_contributions = SerializerMethodField()

    class Meta:
        model = PurchaseRequest
        fields = ["id", "precious_item", "asset_contributions"]

    def get_asset_contributions(self, obj):
        """
        Returns a list of all assets contributed to the pool or Musharakah.
        Each item includes contribution type, related pool or musharakah contract ID, quantity, and created date.
        """
        business = get_business_from_user_token(self.context["request"], "business")
        contributions = (
            AssetContribution.objects.filter(
                purchase_request=obj,
                status__in=[RequestStatus.PENDING, RequestStatus.APPROVED],
            )
            .select_related("pool", "musharakah_contract_request")
            .only(
                "contribution_type",
                "quantity",
                "created_at",
                "pool__id",
                "musharakah_contract_request__id",
            )
        )

        result = []
        for contribution in contributions:
            item = {
                "contribution_type": contribution.contribution_type,
                "quantity": contribution.quantity,
                "created_at": contribution.created_at,
            }

            if contribution.contribution_type == ContributionType.POOL:
                pool = contribution.pool
                musharakah = getattr(pool, "musharakah_contract_request", None)

                # Only include if the pool is linked to a musharakah owned by the current jeweler
                if musharakah and musharakah.jeweler == business:
                    item["pool_id"] = pool.id
                else:
                    continue  # Skip all other cases

            elif (
                contribution.contribution_type == ContributionType.MUSHARAKAH
                and contribution.musharakah_contract_request
                and contribution.musharakah_contract_request.jeweler == business
            ):
                item[
                    "musharakah_contract_request_id"
                ] = contribution.musharakah_contract_request_id

            else:
                continue  # Skip all unrelated musharakah contributions

            result.append(item)

        return result


########################################################################################
################################ Pool's Serializer #####################################
########################################################################################


class AssetContributionSerializer(ModelSerializer):
    """Serializer for Asset Contribution."""

    class Meta:
        model = AssetContribution
        fields = ["purchase_request", "fullname", "quantity", "contribution_type"]


class PoolPurchaseRequestContributionSerializer(ModelSerializer):
    """Serializer for Pool Purchase Request Contribution."""

    precious_item = PreciousItemBaseSerializer()

    class Meta:
        model = PurchaseRequest
        fields = [
            "id",
            "precious_item",
            "business",
        ]


class AssetContributionResponseSerializer(serializers.ModelSerializer):
    """Serializer for Asset Contribution."""

    purchase_request = PoolPurchaseRequestContributionSerializer()

    class Meta:
        model = AssetContribution
        fields = [
            "id",
            "purchase_request",
            "fullname",
            "quantity",
            "contribution_type",
            "status",
        ]


class AssetContributionSummarySerializer(serializers.ModelSerializer):
    """Serializer to flatten AssetContribution and merge PurchaseRequest data."""

    id = serializers.CharField(source="purchase_request.id")
    precious_item = PreciousItemBaseSerializer(source="purchase_request.precious_item")
    business = serializers.SerializerMethodField()

    class Meta:
        model = AssetContribution
        fields = [
            "id",
            "precious_item",
            "created_by",
            "business",
            # AssetContribution-specific fields
            "fullname",
            "quantity",
            "contribution_type",
        ]

    def get_business(self, obj):
        business = getattr(obj.purchase_request, "business", None)
        if not business:
            return None
        return {
            "id": business.id,
            "name": business.name,
        }


class PoolSerializer(ModelSerializer):
    """Serializer for Pool model."""

    organization_logo = serializers.SerializerMethodField()
    logo = serializers.SerializerMethodField()
    material_item = serializers.CharField(source="material_item.name", read_only=True)

    class Meta:
        model = Pool
        fields = [
            "id",
            "name",
            "target",
            "remaining_target",
            "material_type",
            "material_item",
            "risk_level",
            "equity_min",
            "equity_max",
            "max_musharakah_weight",
            "penalty_amount",
            "created_at",
            "updated_at",
            "organization_logo",
            "logo",
        ]

    def get_organization_logo(self, obj):
        user = self.context.get("request").user
        organization_logo = user.organization_id.logo
        return (
            get_presigned_url_from_s3(user.organization_id.logo)
            if organization_logo
            else None
        )

    def get_logo(self, obj):
        """Generate a presigned URL for the pool logo using the PresignedUrlSerializer."""
        return get_presigned_url_from_s3(obj.logo) if obj.logo else None


class PoolAssetContributionSerializer(serializers.Serializer):
    # Update purchase_request field to auto fetch with related
    purchase_request = serializers.PrimaryKeyRelatedField(
        queryset=PurchaseRequest.objects.select_related(
            "precious_item__precious_metal",
            "precious_item__carat_type",
            "precious_item__material_item",
            "precious_item__precious_stone__shape_cut",
        )
    )

    class Meta:
        model = AssetContribution
        fields = ["purchase_request", "fullname", "quantity", "contribution_type"]


class PoolContributionResponseSerializer(serializers.ModelSerializer):
    asset_contributions = AssetContributionResponseSerializer(many=True)
    pool = serializers.SerializerMethodField()
    organization_logo = serializers.SerializerMethodField()

    class Meta:
        model = PoolContribution
        fields = [
            "id",
            "pool",
            "asset_contributions",
            "signature",
            "created_at",
            "organization_logo",
        ]

    def get_organization_logo(self, obj):
        """Generate a presigned URL for the logo in the model using the PresignedUrlSerializer."""
        user = self.context.get("request").user
        return get_presigned_url_from_s3(user.organization_id.logo)

    def get_pool(self, obj):
        """Generate a presigned URL for the logo in the model using the PresignedUrlSerializer."""
        data = {"id": obj.pool.id, "name": obj.pool.name}
        return data


class PoolContributionSerializer(serializers.ModelSerializer):
    asset_contributions = AssetContributionSerializer(many=True, required=True)

    class Meta:
        model = PoolContribution
        fields = ["id", "pool", "asset_contributions", "signature", "created_at"]
        read_only = ["id", "created_at"]

    def validate(self, attrs):
        asset_contributions = attrs.get("asset_contributions", [])
        request = self.context["request"]

        business = get_business_from_user_token(request, "business")
        pool = attrs.get("pool")

        if not business:
            raise ValidationError(MESSAGES["business_account_not_found"])

        if not asset_contributions:
            raise ValidationError(MESSAGES["asset_contribution_required"])

        if all(value == 0 for value in pool.remaining_target.values()):
            raise ValidationError(MESSAGES["pool_target_achieved"])

        remaining_target = pool.remaining_target

        # Calculate total weight being contributed
        total_contributed_weight = Decimal("0.00")
        for asset in asset_contributions:
            quantity = asset["quantity"]
            purchase_request = asset["purchase_request"]

            # Check quantity must be a greater then zero
            if quantity <= 0:
                raise ValidationError(MESSAGES["quantity_must_be_greater_zero"])

            # Calculate weight for this asset
            precious_item = purchase_request.precious_item
            if precious_item.material_type == MaterialType.METAL:
                weight_per_unit = precious_item.precious_metal.weight
            elif precious_item.material_type == MaterialType.STONE:
                weight_per_unit = precious_item.precious_stone.weight
            else:
                weight_per_unit = None

            if weight_per_unit:
                total_contributed_weight += Pool.quantize(quantity * weight_per_unit)

        # Check minimum contribution requirement with exception
        # Exception: When remaining target < minimum, allow contribution less than minimum
        minimum_required = pool.minimum_investment_grams_per_participant
        if minimum_required and minimum_required > 0:
            # Get remaining target (for simple pools without musharakah)
            # For musharakah pools, remaining_target has "metal" and "stone" dicts,
            # so minimum check exception only applies to simple pools with "total_remaining"
            remaining_weight = remaining_target.get("total_remaining", None)

            if remaining_weight is not None:
                # Calculate ALL PENDING contributions from ALL users for this pool
                # This is important because we need to know the true remaining after all pending contributions
                all_pending_contributions = pool.pool_contributions.filter(
                    status=RequestStatus.PENDING
                )

                # Get asset contributions from all pending pool contributions
                all_pending_asset_contributions = AssetContribution.objects.filter(
                    pool_contributor__in=all_pending_contributions, pool=pool
                )

                # Calculate total weight of ALL pending contributions (from all users)
                all_pending_weight = Decimal("0.00")
                if all_pending_asset_contributions.exists():
                    all_pending_weight = get_total_weight_of_all_asset_contributed(
                        all_pending_asset_contributions
                    )

                # Calculate actual remaining after considering ALL pending contributions
                # This gives us the true remaining that can still be contributed
                actual_remaining = remaining_weight - all_pending_weight

                # Check if actual remaining is less than minimum
                if actual_remaining < minimum_required:
                    # Exception: actual remaining is less than minimum, so allow any contribution
                    # that doesn't exceed actual remaining (even if less than minimum)
                    if total_contributed_weight > actual_remaining:
                        # Format values to 2 decimal places for display
                        formatted_weight = f"{total_contributed_weight:.2f}".rstrip(
                            "0"
                        ).rstrip(".")
                        # If actual_remaining is negative or zero, show 0.00g
                        display_remaining = max(actual_remaining, Decimal("0.00"))
                        formatted_remaining = f"{display_remaining:.2f}".rstrip(
                            "0"
                        ).rstrip(".")
                        raise ValidationError(
                            f"Contribution weight ({formatted_weight}g) exceeds remaining target ({formatted_remaining}g)"
                        )
                    # Allow contribution even if less than minimum (exception case)
                else:
                    # Normal case: actual remaining >= minimum, so enforce minimum requirement
                    if total_contributed_weight < minimum_required:
                        # Format values to 2 decimal places for display
                        formatted_minimum = f"{minimum_required:.2f}".rstrip(
                            "0"
                        ).rstrip(".")
                        formatted_weight = f"{total_contributed_weight:.2f}".rstrip(
                            "0"
                        ).rstrip(".")
                        raise ValidationError(
                            f"Minimum contribution required is {formatted_minimum}g, but provided weight is {formatted_weight}g"
                        )
            # For musharakah pools (no "total_remaining"), minimum check is not applied
            # as they have specific material requirements that are validated separately

        for asset in asset_contributions:
            quantity = asset["quantity"]
            purchase_request = asset["purchase_request"]
            self._validate_asset(purchase_request, quantity, remaining_target)

        return attrs

    def _validate_asset(self, purchase_request, quantity, remaining_target):
        precious_item = purchase_request.precious_item
        material_type = precious_item.material_type

        if material_type == MaterialType.METAL:
            self._validate_metal(purchase_request, quantity, remaining_target)
        elif material_type == MaterialType.STONE:
            self._validate_stone(purchase_request, quantity, remaining_target)
        else:
            raise ValidationError(MESSAGES["asset_contribution_material_mismatch"])

    def _validate_metal(self, purchase_request, quantity, remaining_target):
        precious_item = purchase_request.precious_item
        material_item_name = precious_item.material_item.name
        carat_name = precious_item.carat_type.name if precious_item.carat_type else None
        weight_per_unit = precious_item.precious_metal.weight

        if weight_per_unit is None:
            raise ValidationError(MESSAGES["missing_weight_info"])

        contributed_weight = Pool.quantize(quantity * weight_per_unit)

        try:
            if "total_remaining" in remaining_target:
                remaining_weight = remaining_target["total_remaining"]
            else:
                remaining_weight = remaining_target["metal"][material_item_name][
                    carat_name
                ]
        except KeyError:
            raise ValidationError(MESSAGES["asset_contribution_material_mismatch"])

        if contributed_weight > remaining_weight:
            raise ValidationError(
                f"{MESSAGES['selected_asset_contribution_exceeds_required_weight']} [{material_item_name} - {carat_name}]"
            )

    def _validate_stone(self, purchase_request, quantity, remaining_target):
        precious_item = purchase_request.precious_item
        material_item_name = precious_item.material_item.name
        shape_cut_name = (
            precious_item.precious_stone.shape_cut.name
            if precious_item.precious_stone.shape_cut
            else None
        )
        weight_per_unit = precious_item.precious_stone.weight

        if weight_per_unit is None:
            raise ValidationError(MESSAGES["missing_weight_info"])

        weight_str = str(Pool.quantize(weight_per_unit))
        contributed_quantity = int(quantity)

        try:
            remaining_quantity = remaining_target["stone"][material_item_name][
                shape_cut_name
            ][weight_str]
        except KeyError:
            raise ValidationError(MESSAGES["asset_contribution_material_mismatch"])

        if contributed_quantity > remaining_quantity:
            raise ValidationError(
                f"{MESSAGES['selected_asset_contribution_exceeds_required_weight']} [{material_item_name} - {shape_cut_name} - {weight_str}]"
            )

    def create(self, validated_data):
        request = self.context["request"]
        pool = validated_data.get("pool")
        asset_contributions = validated_data.pop("asset_contributions", [])

        business = get_business_from_user_token(request, "business")
        validated_data["participant"] = business

        pool_contribution = PoolContribution.objects.create(**validated_data)

        # This method is assumed to create contributions and return total weight
        asset_contributions_weight = create_manual_contributions(
            asset_contributions, request.user, business, pool, pool_contribution
        )

        if asset_contributions_weight:
            pool_contribution.weight = asset_contributions_weight
            pool_contribution.save()

            # Note: Pool status should only be checked when a contribution is APPROVED,
            # not when it's created as PENDING. The check is handled in
            # PoolContributionUpdateAPIView when admin approves a contribution.
            # PENDING contributions don't count towards the target.

            return pool_contribution

        raise ValidationError(MESSAGES["asset_not_enough_in_pool"])

    def _get_precious_item_weight(self, purchase_request, material_type):
        # Return the weight of a metal or stone item from the purchase request.
        if material_type == MaterialType.METAL:
            return purchase_request.precious_item.precious_metal.weight
        return purchase_request.precious_item.precious_stone.weight

    def _is_pool_fulfilled(self, remaining_target):
        """Determines if the pool's contribution target has been fulfilled."""

        if "total_remaining" in remaining_target:
            return remaining_target["total_remaining"] <= 0

        return self._is_metal_fulfilled(
            remaining_target.get("metal", {})
        ) and self._is_stone_fulfilled(remaining_target.get("stone", {}))

    def _is_metal_fulfilled(self, metal_target):
        """Checks if all metal material requirements have been fulfilled."""

        return all(
            remaining_weight <= 0
            for item_dict in metal_target.values()
            for remaining_weight in item_dict.values()
        )

    def _is_stone_fulfilled(self, stone_target):
        """Checks if all stone material requirements have been fulfilled."""

        return all(
            remaining_quantity <= 0
            for shape_dicts in stone_target.values()
            for weight_dict in shape_dicts.values()
            for remaining_quantity in weight_dict.values()
        )


########################################################################################
############################ Taqabeth Enfocer Serializer's ############################
################################ USED for the Admin ####################################


class OccupiedAssetContributionSerializer(serializers.ModelSerializer):
    purchase_request = PoolPurchaseRequestContributionSerializer()

    class Meta:
        model = AssetContribution
        exclude = ["restored_at", "deleted_at", "transaction_id"]


class OccupiedAssetContributionDetailSerializer(serializers.ModelSerializer):
    purchase_request = PoolPurchaseRequestContributionSerializer()
    pool = serializers.SerializerMethodField()
    musharakah_contract_request = BaseMusharakahContractRequestResponseSerializer()
    jewelry_production = serializers.SerializerMethodField()
    allocated_serial_numbers = serializers.SerializerMethodField()

    class Meta:
        model = AssetContribution
        exclude = ["restored_at", "deleted_at", "transaction_id"]

    def get_pool(self, obj):
        """Return pool details with context."""
        try:
            if obj.pool:
                return PoolResponseSerializer(
                    obj.pool, context={"request": self.context.get("request")}
                ).data
        except Exception:
            pass
        return None

    def get_jewelry_production(self, obj):
        """Return jewelry production details if available."""
        try:
            # Import here to avoid circular imports
            from manufacturer.models import ProductionPaymentAssetAllocation
            from manufacturer.serializers import JewelryProductionDetailSerializer

            # Try to get production payment related to this asset contribution
            allocation = (
                ProductionPaymentAssetAllocation.objects.filter(
                    precious_item_unit_musharakah__precious_item_unit__purchase_request=obj.purchase_request
                )
                .select_related("production_payment__jewelry_production")
                .first()
            )

            if allocation and allocation.production_payment.jewelry_production:
                return JewelryProductionDetailSerializer(
                    allocation.production_payment.jewelry_production,
                    context={"request": self.context.get("request")},
                ).data
        except Exception:
            pass
        return None

    def get_allocated_serial_numbers(self, obj):
        """
        Get serial numbers that are allocated to THIS specific asset contribution.
        Only returns units linked to the actual musharakah contract or pool.
        """
        try:
            units_queryset = None

            # Filter based on contribution type
            if obj.contribution_type == ContributionType.MUSHARAKAH:
                # Only get units linked to THIS musharakah contract
                if obj.musharakah_contract_request:
                    units_queryset = obj.purchase_request.precious_item_units.filter(
                        musharakah_contract=obj.musharakah_contract_request
                    )

            elif obj.contribution_type == ContributionType.POOL:
                # Only get units linked to THIS pool
                if obj.pool:
                    units_queryset = obj.purchase_request.precious_item_units.filter(
                        pool=obj.pool
                    )

            if units_queryset is None:
                return []

            if not units_queryset.exists():
                return []

            # Serialize the units with their serial numbers and remaining weights
            return AdminPreciousItemUnitSerializer(units_queryset, many=True).data

        except Exception as e:
            return []


########################################################################################
################################ Musharakah Contract Request Serializers ################
########################################################################################


class AssetContributionPreviewSerializer(serializers.Serializer):
    """Serializer for asset contribution preview - simplified version."""

    purchase_request = serializers.CharField(required=True)
    quantity = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=True, min_value=Decimal("0.00")
    )

    def validate_quantity(self, value):
        """Validate quantity is greater than or equal to zero."""
        # Allow 0, but it will be filtered out in parent serializer
        if value < 0:
            raise ValidationError(MESSAGES["quantity_must_be_greater_zero"])
        return value

    def validate_purchase_request(self, value):
        """Validate purchase request ID format."""
        if not value or not isinstance(value, str):
            raise ValidationError(MESSAGES["purchase_request_not_found"])
        return value


class MusharakahContractAgreementPreviewSerializer(serializers.Serializer):
    """Serializer for previewing Musharakah Contract Agreement with proposed contributions."""

    asset_contributions = AssetContributionPreviewSerializer(
        many=True, required=False, allow_empty=True
    )

    def validate_asset_contributions(self, value):
        """Validate that asset contributions are provided and valid.

        Filters out contributions with quantity <= 0 to handle cases where
        frontend sends zero values (e.g., when items are unselected).
        If all contributions are filtered out, returns empty list which will
        cause the view to fall back to saved asset_contributions.
        """
        if not value:
            # Allow empty list for initial template render, but validate items when provided
            return []

        # Filter out contributions with invalid quantities (<= 0) instead of raising error
        # This handles cases where frontend sends 0.0 values
        filtered_contributions = []
        for contribution in value:
            quantity = contribution.get("quantity")
            # Only include contributions with valid quantity > 0
            if quantity is not None and quantity > 0:
                filtered_contributions.append(contribution)

        return filtered_contributions


class MusharakahContractRequestAssetContributionSerializer(ModelSerializer):
    """Serializer for Musharakah Contract Request Asset Contribution."""

    asset_contributions = AssetContributionSerializer(many=True, required=False)
    all_asset = serializers.BooleanField()

    class Meta:
        model = MusharakahContractRequest
        fields = ["all_asset", "asset_contributions", "investor_signature"]

    def validate(self, attrs):
        all_asset = attrs.get("all_asset")
        asset_contributions = attrs.get("asset_contributions")
        if self.instance.investor:
            raise ValidationError(
                MESSAGES["musharakah_contract_request_already_investor_assigned"]
            )

        # TODO: Implement "Select All" feature to enable automatic asset contributions.
        # Currently, only manual contributions are supported.
        # The following code is prepared for future integration of the "Select All" feature,
        # which will allow automatic assignment of assets matching the material requirements.
        # Once implemented, manual contribution restrictions should be adjusted accordingly.

        # # If all assets to be auto-assigned, check if business has enough matching assets
        # if all_asset:
        #     business = get_business_from_user_token(self.context["request"], "business")

        #     purchase_requests = PurchaseRequest.objects.select_related(
        #         "precious_item__precious_metal", "precious_item__precious_stone"
        #     ).filter(business=business, request_type=RequestType.PURCHASE)

        #     requested_quantities = (
        #         self.instance.musharakah_contract_request_quantities.select_related(
        #             "jewelry_product"
        #         ).prefetch_related("jewelry_product__product_materials")
        #     )

        #     # Check if fulfillment is possible with available assets
        #     if not self._is_fulfillment_possible(
        #         requested_quantities, purchase_requests
        #     ):
        #         raise ValidationError(
        #             MESSAGES["assets_not_enough_in_musharakah_conract_request"]
        #         )

        # If not all_asset and not manual contributions provided
        if not all_asset and not asset_contributions:
            raise ValidationError(MESSAGES["asset_contribution_required"])

        # If manual contributions are provided
        if not all_asset and asset_contributions:
            self._validate_manual_asset_contribution_weights_against_requirements(
                asset_contributions
            )

        return attrs

    def update(self, instance, validated_data):
        asset_contributions = validated_data.pop("asset_contributions", [])
        request = self.context["request"]
        user = request.user
        business = get_business_from_user_token(request, "business")
        assign_all_assets = validated_data.get("all_asset")
        investor_signature = validated_data.get("investor_signature")

        if not assign_all_assets:
            for contribution in asset_contributions:
                purchase_request = contribution.get("purchase_request")
                if not purchase_request:
                    continue
                contribution["price_locked"] = self._get_asset_unit_price_locked(
                    purchase_request
                )
                contribution["contribution_type"] = ContributionType.MUSHARAKAH

            create_manual_contributions(
                asset_contributions=asset_contributions,
                user=user,
                business=business,
                musharakah_contract_request=instance,
            )
        else:
            purchase_requests = PurchaseRequest.objects.select_related(
                "precious_item__precious_metal", "precious_item__precious_stone"
            ).filter(business=business, request_type=RequestType.PURCHASE)

            requested_quantities = (
                instance.musharakah_contract_request_quantities.select_related(
                    "jewelry_product"
                ).prefetch_related("jewelry_product__product_materials")
            )

            contributions = self._generate_contributions(
                requested_quantities, purchase_requests, instance, user, business
            )
            AssetContribution.objects.bulk_create(contributions)

        instance.investor = business
        instance.musharakah_contract_status = MusharakahContractStatus.ACTIVE
        instance.investor_signature = investor_signature
        instance.updated_by = user
        instance.updated_at = timezone.now()
        instance.save()
        return instance

    def _validate_manual_asset_contribution_weights_against_requirements(
        self, asset_contributions
    ):
        """Ensure manually contributed assets do not exceed required weight for materials."""

        # Step 1: Retrieve all material requirements from the database
        # For each material used in the jewelry products linked to the Musharakah contract request,
        # calculate the total required weight based on product weight and requested quantity.
        required_materials = (
            JewelryProductMaterial.objects.select_related(
                "material_type",
                "material_item",
                "carat_type",
                "shape_cut",
                "jewelry_product",
            )
            .prefetch_related("jewelry_product__musharakah_contract_request_quantities")
            .filter(
                jewelry_product__musharakah_contract_request_quantities__musharakah_contract_request=self.instance
            )
            .annotate(
                required_weight=Case(
                    # For stones: quantity * contract_request_quantity * weight
                    When(
                        material_type=MaterialType.STONE,
                        then=ExpressionWrapper(
                            F("quantity")
                            * F(
                                "jewelry_product__musharakah_contract_request_quantities__quantity"
                            )
                            * F("weight"),
                            output_field=DecimalField(max_digits=20, decimal_places=2),
                        ),
                    ),
                    # For others (metals, etc.): weight * contract_request_quantity
                    default=ExpressionWrapper(
                        F("weight")
                        * F(
                            "jewelry_product__musharakah_contract_request_quantities__quantity"
                        ),
                        output_field=DecimalField(max_digits=20, decimal_places=2),
                    ),
                    output_field=DecimalField(max_digits=20, decimal_places=2),
                )
            )
            .values(
                "material_type",
                "material_item_id",
                "carat_type_id",
                "shape_cut_id",
                "clarity",  # if required for stones
                "color_id",  # if required for diamonds
            )
            .annotate(total_required_weight=Sum("required_weight"))
        )

        # Step 2: Build a dictionary (material_requirements) to map each unique material specification
        # to its total required weight for quick lookup and comparison during validation.
        material_requirements = {}
        for item in required_materials:
            color_id = item.get("color_id")
            if item["material_type"] == MaterialType.METAL:
                key = (
                    item["material_type"],
                    item["material_item_id"],
                    item["carat_type_id"],
                )
            elif item["material_type"] == MaterialType.STONE:
                if color_id:  # for only diamonds
                    key = (
                        item["material_type"],
                        item["material_item_id"],
                        item["shape_cut_id"],
                        item["clarity"],
                        color_id,
                    )
                else:
                    key = (
                        item["material_type"],
                        item["material_item_id"],
                        item["shape_cut_id"],
                    )
            else:
                key = (item["material_type"], item["material_item_id"])

            material_requirements[key] = (
                material_requirements.get(key, Decimal("0"))
                + item["total_required_weight"]
            )

        # Step 3: Iterate over each manually contributed asset and validate it against the requirements
        for contribution in asset_contributions:
            purchase_request = contribution.get("purchase_request")
            quantity = contribution.get("quantity", 0)

            # Ensure the purchase request is valid
            if not purchase_request or not isinstance(
                purchase_request, PurchaseRequest
            ):
                raise ValidationError("Invalid or missing purchase_request instance.")

            # Identify the material and its properties from the asset
            item = purchase_request.precious_item
            material_type = item.material_type
            material_item = item.material_item
            carat_type = getattr(item, "carat_type", None)
            shape_cut = (
                getattr(item.precious_stone, "shape_cut", None)
                if material_type == MaterialType.STONE
                else None
            )
            color = (
                getattr(item.precious_stone, "color", None)
                if material_type == MaterialType.STONE
                and material_item.name.lower() == "diamond"
                else None
            )
            clarity = (
                getattr(item.precious_stone, "clarity", None)
                if material_type == MaterialType.STONE
                and material_item.name.lower() == "diamond"
                else None
            )

            # This key is used to match the asset against the pre-calculated required materials.
            # The key structure depends on the material type, ensuring we accurately differentiate similar items.
            # For metals, carat_type is ignored to allow allocation of any carat_type material
            if material_type == MaterialType.METAL:
                # For metals, match by material_type and material_item only (ignore carat_type)
                asset_key = (material_type, material_item.id)
                # Find all requirements that match this material_type and material_item (any carat_type)
                matching_keys = [
                    key
                    for key in material_requirements.keys()
                    if len(key) >= 2
                    and key[0] == material_type
                    and key[1] == material_item.id
                ]
                if not matching_keys:
                    raise ValidationError(
                        MESSAGES["asset_contribution_material_mismatch"]
                    )
                # Sum up all required weights for this material (across all carat_types)
                remaining_required_weight = sum(
                    material_requirements[key] for key in matching_keys
                ).quantize(Decimal("0.00"), rounding=ROUND_HALF_UP)
            elif material_type == MaterialType.STONE:
                if material_item.name.lower() == "diamond":
                    asset_key = (
                        material_type,
                        material_item.id,
                        shape_cut.id if shape_cut else None,
                        clarity.id if clarity else None,
                        color.id if color else None,
                    )
                else:
                    asset_key = (
                        material_type,
                        material_item.id,
                        shape_cut.id if shape_cut else None,
                    )
                if asset_key not in material_requirements:
                    raise ValidationError(
                        MESSAGES["asset_contribution_material_mismatch"]
                    )
                remaining_required_weight = material_requirements[asset_key].quantize(
                    Decimal("0.00"), rounding=ROUND_HALF_UP
                )
                matching_keys = [asset_key]
            else:
                asset_key = (material_type, material_item.id)
                if asset_key not in material_requirements:
                    raise ValidationError(
                        MESSAGES["asset_contribution_material_mismatch"]
                    )
                remaining_required_weight = material_requirements[asset_key].quantize(
                    Decimal("0.00"), rounding=ROUND_HALF_UP
                )
                matching_keys = [asset_key]

            # Calculate the total weight of the contributed asset
            weight_per_unit = self._get_precious_item_weight(
                purchase_request, material_type
            )
            contributed_weight = Decimal(quantity) * weight_per_unit
            contributed_weight = contributed_weight.quantize(
                Decimal("0.00"), rounding=ROUND_HALF_UP
            )

            # Ensure the contribution does not exceed the required weight
            if contributed_weight > remaining_required_weight:
                raise ValidationError(
                    MESSAGES["selected_asset_contribution_exceeds_required_weight"]
                )

            # Deduct the contributed weight from the required weight tracker
            # For metals with multiple carat_type requirements, deduct proportionally
            if material_type == MaterialType.METAL and len(matching_keys) > 1:
                # Distribute deduction proportionally based on current requirement weights
                remaining_to_deduct = contributed_weight
                # Sort keys by weight (descending) to deduct from largest first
                sorted_keys = sorted(
                    matching_keys, key=lambda k: material_requirements[k], reverse=True
                )
                for key in sorted_keys:
                    if remaining_to_deduct <= 0:
                        break
                    available = material_requirements[key]
                    deduct_amount = min(remaining_to_deduct, available)
                    material_requirements[key] -= deduct_amount
                    remaining_to_deduct -= deduct_amount
            else:
                # For stones or single matching key, deduct directly
                material_requirements[matching_keys[0]] -= contributed_weight
        # Step 4: After all contributions, check if any required weight is still left unfulfilled
        incomplete_material_requirements = {
            key: weight.quantize(Decimal("0.00"), rounding=ROUND_HALF_UP)
            for key, weight in material_requirements.items()
            if weight > Decimal("0")
        }

        # Raise an error if any material is still missing contributions
        if incomplete_material_requirements:
            raise ValidationError(
                MESSAGES["assets_not_enough_in_musharakah_conract_request"]
            )

    def _is_fulfillment_possible(self, requested_quantities, purchase_requests):
        # Create a list of (material, total required weight) pairs for all requested quantities.
        material_requirements = [
            (material, request_quantity.quantity * material.weight)
            for request_quantity in requested_quantities
            for material in request_quantity.jewelry_product.product_materials.all()
        ]

        # Check each material to see if user has enough available weight to fulfill the request.
        for material, required_weight in material_requirements:
            # Get all purchase requests that are related to the current material.
            purchase_requests_based_on_material = (
                self._get_purchase_requests_based_on_material(
                    material, purchase_requests
                )
            )

            # Calculate the total available weight from the purchase requests.
            total_available_weight = sum(
                int(purchase_request.remaining_quantity)
                * self._get_precious_item_weight(
                    purchase_request, material.material_type
                )
                for purchase_request in purchase_requests_based_on_material
            )
            if total_available_weight < required_weight:
                return False

        return True

    def _generate_contributions(
        self, requested_quantities, purchase_requests, instance, user, business
    ):
        # Automatically generate a list of AssetContribution objects based on available assets
        contributions = []

        # Calculate the total required weight for each material in the requested jewelry products:
        # - Iterate through each requested quantity and its associated jewelry product materials
        # - Multiply the requested quantity by the material's weight to get the total weight needed
        # - Only include materials with a total weight greater than 0
        material_requirements = [
            (material, request_quantity.quantity * material.weight)
            for request_quantity in requested_quantities
            for material in request_quantity.jewelry_product.product_materials.all()
            if (request_quantity.quantity * material.weight) > 0
        ]

        for material, required_weight in material_requirements:
            # Get all purchase requests that are related to the current material.
            purchase_requests_based_on_material = (
                self._get_purchase_requests_based_on_material(
                    material, purchase_requests
                )
            )

            # Filter purchase request queryset based on material.
            for purchase_request in purchase_requests_based_on_material:
                if required_weight <= 0:
                    break

                # Item weight for metal as per metal and stone.
                item_weight = self._get_precious_item_weight(
                    purchase_request, material.material_type
                )
                available_qty = int(purchase_request.remaining_quantity or 0)

                # Check item weight and available quantity should be greate then zero
                if item_weight <= 0 or available_qty <= 0:
                    continue

                # Calculate the maximum number of units that can be used to fulfill the remaining required weight
                max_quantity_required = int(required_weight // item_weight)
                if max_quantity_required <= 0:
                    continue

                # Assign the number of units that can be contributed
                assigned_qty = min(available_qty, max_quantity_required)

                # Update the remaining required weight after this contribution
                required_weight -= assigned_qty * item_weight

                contributions.append(
                    AssetContribution(
                        purchase_request=purchase_request,
                        business=business,
                        quantity=assigned_qty,
                        contribution_type=ContributionType.MUSHARAKAH,
                        musharakah_contract_request=instance,
                        created_by=user,
                        price_locked=self._get_asset_unit_price_locked(
                            purchase_request
                        ),
                    )
                )

        return contributions

    def _get_asset_unit_price_locked(self, purchase_request):
        precious_item = purchase_request.precious_item
        base_price = Decimal(str(purchase_request.price_locked or 0))

        if precious_item.material_type == MaterialType.METAL:
            metal = getattr(precious_item, "precious_metal", None)
            weight = getattr(metal, "weight", None) if metal else None
            if weight is None:
                return Decimal("0.0000")
            unit_price = base_price * Decimal(str(weight))
        else:
            unit_price = base_price

        try:
            return unit_price.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError):
            return Decimal("0.0000")

    def _get_purchase_requests_based_on_material(self, material, purchase_requests):
        # Return purchase requests that match the given material.
        if material.material_type == MaterialType.METAL:
            # Filter purchase requests for METAL materials:
            # - The precious item's material type must be METAL
            # - The material item ID must match (ensures the specific metal type, e.g., gold vs. silver)
            # - The carat type must match exactly (e.g., 14K, 18K, etc.).
            return [
                purchase_request
                for purchase_request in purchase_requests
                if purchase_request.precious_item.material_type == MaterialType.METAL
                and purchase_request.precious_item.material_item_id
                == material.material_item_id
                and purchase_request.precious_item.carat_type == material.carat_type
            ]
        else:
            # Otherwise, if the material type is STONE,:
            # - The precious item material type is STONE (to match the requested stone)
            # - The material_item_id matches exactly (ensures the specific stone type is the same)
            # - The precious_stone shape_cut matches (e.g., round, princess, emerald, cuts, etc)
            return [
                purchase_request
                for purchase_request in purchase_requests
                if purchase_request.precious_item.material_type == MaterialType.STONE
                and purchase_request.precious_item.material_item_id
                == material.material_item_id
                and purchase_request.precious_item.precious_stone.shape_cut
                == material.shape_cut
            ]

    def _get_precious_item_weight(self, purchase_request, material_type):
        # Return the weight of a metal or stone item from the purchase request.
        if material_type == MaterialType.METAL:
            return purchase_request.precious_item.precious_metal.weight
        return purchase_request.precious_item.precious_stone.weight


class MusharakahContractRequestSummarySerializer(Serializer):
    total_count = serializers.IntegerField()
    active_count = serializers.IntegerField()
    expired_count = serializers.IntegerField()


class MusharakahContractProfitSerializer(Serializer):
    """Serializer for musharakah contract profit response."""

    total_profit = serializers.DecimalField(
        max_digits=20,
        decimal_places=2,
        help_text="Total profit from musharakah contracts",
    )


class PoolSummarySerializer(Serializer):
    total_count = serializers.IntegerField()
    total_open_count = serializers.IntegerField()
    total_closed_count = serializers.IntegerField()
    total_settled_count = serializers.IntegerField()


class PortfolioHistorySerializer(serializers.Serializer):
    id = serializers.CharField()
    type = serializers.CharField()
    created_at = serializers.DateTimeField()
    data = serializers.DictField()


class LogisticCostPaymentSerializer(serializers.Serializer):
    musharakah_contract_id = serializers.CharField(write_only=True, required=True)


class RefiningCostPaymentSerializer(LogisticCostPaymentSerializer):
    pass


class MusharakahContractEarlyTerminationPaymentSerializer(
    LogisticCostPaymentSerializer
):
    pass


class SerialNumberValidationSerializer(serializers.Serializer):
    """
    Serializer to validate serial number uniqueness.

    Use cases:
    1. serial_number + purchase_request_id
    2. system_serial_number (global uniqueness)
    """

    purchase_request_id = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    serial_number = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    system_serial_number = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    def validate(self, data):
        serial_number = data.get("serial_number", "").strip()
        system_serial_number = data.get("system_serial_number", "").strip()
        purchase_request_id = data.get("purchase_request_id", "").strip()

        # Must provide at least one serial number
        if not serial_number and not system_serial_number:
            raise serializers.ValidationError(
                MESSAGES["invalid_serial_validation_request"]
            )

        # serial_number requires purchase_request_id
        if serial_number and not purchase_request_id:
            raise serializers.ValidationError(MESSAGES["purchase_request_id_required"])

        data["serial_number"] = serial_number
        data["system_serial_number"] = system_serial_number
        data["purchase_request_id"] = purchase_request_id

        return data
