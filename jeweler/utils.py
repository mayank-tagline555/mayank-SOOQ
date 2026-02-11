from datetime import datetime
from datetime import timedelta
from decimal import ROUND_HALF_UP
from decimal import Decimal

from django.db.models import DecimalField
from django.db.models import F
from django.db.models import Sum
from django.template.loader import render_to_string

from account.models import Organization
from jeweler.models import JewelryProductStonePrice
from jeweler.models import ManufacturingProductRequestedQuantity
from jeweler.models import ManufacturingTarget
from jeweler.models import MusharakahContractRequestQuantity
from jeweler.models import ProductionPayment
from sooq_althahab.enums.sooq_althahab_admin import MaterialType


def get_organization_name_from_request(request):
    """Helper to fetch organization name from auth token."""
    organization_code = request.auth.get("organization_code")
    if not organization_code:
        return {"name": "N/A", "arabic_name": "N/A"}
    try:
        organization = Organization.objects.get(code=organization_code)
        return {
            "name": organization.name or "N/A",
            "arabic_name": organization.arabic_name or organization.name or "N/A",
        }
    except Organization.DoesNotExist:
        return {"name": "N/A", "arabic_name": "N/A"}


def generate_contract_details_html(obj, request):
    from django.utils import translation

    from jeweler.serializers import MusharakahContractRequestResponseSerializer

    organization_data = get_organization_name_from_request(request)

    serialized_contract = MusharakahContractRequestResponseSerializer(
        obj, context={"request": request}
    ).data

    # Determine the correct organization name based on request language
    current_language = translation.get_language()
    if current_language == "ar" and organization_data.get("arabic_name"):
        org_name = organization_data["arabic_name"]
    else:
        org_name = organization_data["name"]

    context = {
        "musharakah_contract": generate_musharaka_contract_context(
            obj, serialized_contract
        ),
        "organization_name": org_name,
    }

    html_string = render_to_string(
        "musharakah_contract/musharakah-contract-response.html",
        context,
    )
    return html_string


def generate_musharaka_contract_context(
    musharakah_contract_request,
    serialized_musharakah_contract,
):
    from sooq_althahab.billing.transaction.helpers import get_user_contact_details

    # === Jeweler details ===
    jeweler_data = serialized_musharakah_contract.get("jeweler") or {}
    jeweler_owner = jeweler_data.get("owner") or {}
    jeweler_address = (
        get_user_contact_details(jeweler_owner.get("id"))
        if jeweler_owner.get("id")
        else {}
    )

    # === Investor details ===
    investor_data = serialized_musharakah_contract.get("investor") or {}
    investor_owner = investor_data.get("owner") or {}
    investor_address = (
        get_user_contact_details(investor_owner.get("id"))
        if investor_owner.get("id")
        else {}
    )

    approved_at_str = serialized_musharakah_contract.get("approved_at")
    approved_at = None
    try:
        if approved_at_str:
            approved_at = datetime.fromisoformat(approved_at_str).date()
    except (ValueError, TypeError, AttributeError):
        approved_at = None

    expiry_date_str = serialized_musharakah_contract.get("expiry_date")

    # Safely get expiry_days from duration_in_days
    expiry_days = None
    try:
        if musharakah_contract_request.duration_in_days:
            expiry_days = musharakah_contract_request.duration_in_days.days
    except (AttributeError, TypeError):
        expiry_days = None

    # Calculate expiry_date properly with safe error handling
    expiry_date = None
    try:
        if expiry_date_str:
            expiry_date = datetime.fromisoformat(expiry_date_str).date()
        elif approved_at and expiry_days:
            # Calculate expiry date from approved_at + days
            expiry_date = approved_at + timedelta(days=expiry_days)
    except (ValueError, TypeError, AttributeError):
        expiry_date = None
    # If neither expiry_date_str nor approved_at+expiry_days, expiry_date remains None
    # and we'll show expiry_days in the template instead

    # === Jewelry Designs & Materials ===
    materials = []
    designs = []
    design_value = Decimal("0.00")

    designs_data = (
        serialized_musharakah_contract.get("musharakah_contract_designs", []) or []
    )

    jewelry_products = [
        product
        for item in designs_data
        for product in (item.get("design", {}).get("jewelry_products") or [])
    ]

    quantities_map = {
        requested_quantity.get("jewelry_product"): requested_quantity.get("quantity")
        for requested_quantity in serialized_musharakah_contract.get(
            "musharakah_contract_request_quantities", []
        )
    }

    # Calculate total precious items value of all precious item contributions (price_locked × quantity)
    precious_items_value = musharakah_contract_request.asset_contributions.aggregate(
        total=Sum(
            F("quantity") * F("price_locked"),
            output_field=DecimalField(max_digits=20, decimal_places=2),
        )
    )["total"] or Decimal("0.00")

    precious_items_value = precious_items_value.quantize(
        Decimal("0.00"), rounding=ROUND_HALF_UP
    )

    for product in jewelry_products:
        product_name = product.get("product_name", "N/A")
        product_id = product.get("id")
        price = Decimal(str(product.get("price", 0) or 0))
        designs.append(product_name)
        design_value += price

        for material in product.get("product_materials", []) or []:
            material_data = {
                "item": material.get("material_item", "N/A"),
                "quantity": quantities_map.get(product_id, material.get("quantity", 0)),
                "weight": material.get("weight", 0),
                "weight_unit": "g"
                if material.get("material_type") == MaterialType.METAL
                else "ct",
                "carat_type": material.get("carat_type", "N/A"),
                "type": material.get("material_type", "N/A"),
            }
            materials.append(material_data)

    investor_signature = serialized_musharakah_contract.get("investor_signature") or {}
    investor_signature_url = (
        investor_signature.get("url", "")
        if isinstance(investor_signature, dict)
        else ""
    )

    jeweler_signature = serialized_musharakah_contract.get("jeweler_signature") or {}
    jeweler_signature_url = (
        jeweler_signature.get("url", "") if isinstance(jeweler_signature, dict) else ""
    )

    return {
        "jeweler": {
            "name": jeweler_data.get("name") or jeweler_owner.get("name", "N/A"),
            "address": jeweler_address.get("address", "N/A"),
            "country": jeweler_address.get("country", "N/A"),
            "phone": jeweler_owner.get("phone_number", "N/A"),
        },
        "investor": {
            "name": investor_data.get("name") or investor_owner.get("name", "N/A"),
            "address": investor_address.get("address", "N/A"),
            "country": investor_address.get("country", "N/A"),
            "phone": investor_owner.get("phone_number", "N/A"),
        },
        "materials": materials,
        "designs": designs,
        "precious_items_value": precious_items_value,
        "design_value": design_value,
        "business_capital_value": str(
            (precious_items_value + design_value).quantize(Decimal("0.01"))
        ),
        "penalty_amount": serialized_musharakah_contract.get(
            "penalty_amount", Decimal("0.00")
        ),
        "expiry_date": expiry_date,
        "expiry_days": expiry_days,
        "investor_profit_sharing_ratio": serialized_musharakah_contract.get(
            "musharakah_equity", 0
        ),
        "jeweler_profit_sharing_ratio": Decimal("100.00")
        - Decimal(str(serialized_musharakah_contract.get("musharakah_equity", 0) or 0)),
        "approved_at": approved_at or "N/A",
        "investor_signature": investor_signature_url,
        "jeweler_signature": jeweler_signature_url,
    }


def send_termination_reciept_email(recipient_list, context, pdf_io, subject):
    from sooq_althahab.tasks import send_mail

    pdf_io.seek(0)
    attachment = [("Tax-Invoice.pdf", pdf_io.read(), "application/pdf")]
    send_mail.delay(
        subject=subject,
        template_name="templates/termination-email.html",
        context=context,
        to_emails=recipient_list,
        attachments=attachment,
    )


def get_musharakah_contract_jewelry_product_count(musharakah_contract):
    payments = ProductionPayment.objects.filter(musharakah_contract=musharakah_contract)

    total_unsold_jewelry_count = 0

    for payment in payments:
        production = payment.jewelry_production

        total_product = ManufacturingProductRequestedQuantity.objects.filter(
            manufacturing_request=production.manufacturing_request
        ).aggregate(total_quantity=Sum("quantity"))
        total_unsold_jewelry_count += total_product.get("total_quantity") or 0

    musharakah_contract_requested_quantity = (
        MusharakahContractRequestQuantity.objects.filter(
            musharakah_contract_request=musharakah_contract
        )
        .aggregate(total_product=Sum("quantity"))
        .get("total_product")
        or 0
    )

    if musharakah_contract_requested_quantity == 0:
        return 0  # avoid division by zero

    remaining_percentage = (
        total_unsold_jewelry_count / musharakah_contract_requested_quantity
    ) * 100

    return round(remaining_percentage, 2)
