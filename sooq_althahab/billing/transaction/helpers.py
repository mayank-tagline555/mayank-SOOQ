from datetime import datetime
from decimal import Decimal

from django.utils.timezone import localtime

from account.models import Address
from account.models import BankAccount
from investor.serializers import TransactionResponseSerializer
from sooq_althahab.billing.subscription.helpers import get_file_url
from sooq_althahab.billing.subscription.helpers import prepare_organization_details
from sooq_althahab.enums.account import TransactionType
from sooq_althahab.enums.account import UserType
from sooq_althahab.utils import get_presigned_url_from_s3

INVOICE_TEMPLATES = {
    TransactionType.PAYMENT: ("invoice/tax-invoice.html", "tax-invoice.pdf"),
    TransactionType.DEPOSIT: ("invoice/top-up-receipt.html", "top-up-receipt.pdf"),
    TransactionType.WITHDRAWAL: (
        "invoice/withdrawal-receipt.html",
        "withdrawal-receipt.pdf",
    ),
}


def get_organization_logo_url(organization):
    """Returns the organization's logo URL, or empty string if not available."""
    if not organization or not organization.logo:
        return get_file_url("static/images/sqa_golden_logo.png")
    logo_url = get_presigned_url_from_s3(organization.logo)
    return logo_url.get("url") if logo_url else ""


def get_transaction_receipt_context_and_template(transaction, organization):
    """Prepare context, template and filename for a given transaction."""
    transaction_data = TransactionResponseSerializer(transaction).data
    transaction_type = transaction.transaction_type

    context = None

    # TODO manage payment condition for subscription payment and purchase request payment
    if (
        transaction_type == TransactionType.PAYMENT
        and transaction.purchase_request is not None
    ):
        context = generate_tax_invoice_context(transaction_data, organization)
    elif transaction_type == TransactionType.DEPOSIT:
        context = generate_deposit_receipt_context(
            transaction, transaction_data, organization
        )
    elif transaction_type == TransactionType.WITHDRAWAL:
        context = generate_withdrawal_receipt_context(
            transaction, transaction_data, organization
        )

    # Invalid type
    if context is None or transaction_type not in INVOICE_TEMPLATES:
        return None, None, None

    context["organization_logo_url"] = get_organization_logo_url(organization)
    template_name, filename = INVOICE_TEMPLATES[transaction_type]
    return context, template_name, filename


def get_user_contact_details(user_id):
    address = Address.objects.filter(user_id=user_id).first()
    if not address:
        return {"address": "", "country": ""}

    def safe(val):
        return val.strip().title() if val else ""

    full_address = ", ".join(
        filter(
            None,
            [
                safe(address.address_line),
                safe(address.city),
                safe(address.country),
                safe(address.pincode),
            ],
        )
    )

    return {
        "address": full_address,
        "country": safe(address.country),
    }


def get_purchase_request_details(purchase_request):
    item = purchase_request["precious_item"]
    data = {
        "material_type": item["material_type"],
        "order_cost": purchase_request["order_cost"],
        "request_type": purchase_request["request_type"],
        "premium": purchase_request["premium"],
        "platform_fee": purchase_request["platform_fee"],
        "vat": purchase_request["vat"],
        "taxes": purchase_request["taxes"],
        "pro_rata_mode": purchase_request["pro_rata_mode"],
        "pro_rata_fee": purchase_request["pro_rata_fee"],
        "annual_pro_rata_fee": purchase_request["annual_pro_rata_fee"],
        "total_cost": purchase_request["total_cost"],
    }

    if item["material_type"] == "metal":
        data.update(
            {
                "name": item["name"],
                "weight": item["precious_metal_details"]["weight"],
                "carat_type": item["carat_type"],
                "rate": purchase_request["price_locked"],
                "requested_quantity": purchase_request["requested_quantity"],
            }
        )
    else:
        details = item["precious_stone_details"]

        data.update(
            {
                "name": item["name"],
                "weight": details["weight"],
                "shape_cut": details["shape_cut"],
                "cut_grade": details["cut_grade"],
                "certificate_type": item["certificate_type"],
                "report_number": item["report_number"],
            }
        )
    return data


def format_datetime(dt):
    local_dt = localtime(dt)
    return local_dt.strftime("%d %B %Y"), local_dt.strftime("%H:%M:%S")


def generate_tax_invoice_context(transaction, organization):
    organization_details = prepare_organization_details(organization)

    from_user = transaction["from_business"]["owner"]
    from_user_address = get_user_contact_details(from_user["id"])

    to_user = transaction["to_business"]["owner"]
    to_user_address = get_user_contact_details(to_user["id"])

    # If the user has a business, use the business name; otherwise, use the user's full name
    name = (
        transaction["from_business"]["name"]
        if from_user["user_type"] == UserType.BUSINESS
        else from_user["name"]
    )

    try:
        date = datetime.fromisoformat(
            transaction.get("purchase_request", {}).get("approved_at")
        ).strftime("%d %B %Y")
    except (TypeError, ValueError):
        date = None

    return {
        "invoice_number": transaction["purchase_request"]["invoice_number"],
        "date": date,
        "bill_to": {
            "name": name,
            "address": from_user_address["address"],
            "country": from_user_address["country"],
            "id": from_user["personal_number"],
            "phone": from_user["phone_number"],
        },
        "sold_by": {
            "name": transaction["to_business"]["name"],
            "address": to_user_address["address"],
            "country": to_user_address["country"],
            "cr_number": transaction["to_business"]["commercial_registration_number"],
            "vat_acc_number": transaction["to_business"]["vat_account_number"],
        },
        "organization_details": organization_details,
        "purchase_request": get_purchase_request_details(
            transaction["purchase_request"]
        ),
        "vat_rate": transaction["vat_rate"],
    }


def generate_deposit_receipt_context(transaction, serialized_transaction, organization):
    organization_details = prepare_organization_details(organization)

    from_business = serialized_transaction["from_business"]
    from_user = from_business["owner"]
    from_user_address = get_user_contact_details(from_user["id"])

    try:
        card_token = transaction.from_business.business_saved_card_tokens.filter(
            is_used_for_subscription=True
        ).first()
        payment_card_number = card_token.number if card_token else ""
    except AttributeError:
        payment_card_number = ""

    date, time = format_datetime(transaction.created_at)
    amount = Decimal(serialized_transaction["amount"] or 0)
    platform_fee = Decimal(serialized_transaction["additional_fee"] or 0)

    # Use business name if available, otherwise use owner's full name
    business_name = (from_business.get("name") or "").strip()
    made_by_name = business_name if business_name else from_user.get("name", "")

    return {
        "organization_details": organization_details,
        "transaction_number": serialized_transaction["receipt_number"],
        "made_by": {
            "name": made_by_name,
            "country": from_user_address["country"],
            "phone_number": from_user.get("phone_number", ""),
        },
        "transaction_type": serialized_transaction["transaction_type"],
        "transfer_via": serialized_transaction["transfer_via"],
        "payment_card_number": payment_card_number,
        "platform_fee": platform_fee,
        "additional_fee": serialized_transaction["additional_fee"] or 0,
        "date": date,
        "time": time,
        "amount": amount,
        "status": serialized_transaction["status"],
        "previous_balance": serialized_transaction["previous_balance"],
        "current_balance": serialized_transaction["current_balance"],
        "total_amount": amount + platform_fee,
        "remark": serialized_transaction["remark"] or "",
    }


def generate_withdrawal_receipt_context(
    transaction, serialized_transaction, organization
):
    organization_details = prepare_organization_details(organization)

    bank_account = organization.organization_bank_accounts.filter(
        deleted_at__isnull=True
    ).first()
    organization_details["iban_code"] = getattr(bank_account, "iban_code", "")

    from_business = serialized_transaction["from_business"]
    from_user = from_business.get("owner", {})
    from_user_id = from_user.get("id")
    from_user_address = (
        get_user_contact_details(from_user_id)
        if from_user_id
        else {"address": "", "country": ""}
    )

    date, time = format_datetime(transaction.created_at)
    amount = transaction.amount or 0
    platform_fee = transaction.additional_fee or 0

    # Use business name if available, otherwise use owner's full name
    business_name = (from_business.get("name") or "").strip()
    transfered_to_name = business_name if business_name else from_user.get("name", "")

    return {
        "organization_details": organization_details,
        "transaction_number": transaction.receipt_number,
        "transfered_to": {
            "name": transfered_to_name,
            "address": from_user_address.get("address", ""),
            "country": from_user_address.get("country", ""),
            "phone": from_user.get("phone_number", ""),
            "cr_number": from_business.get("commercial_registration_number") or "",
        },
        "transaction_type": transaction.transaction_type,
        "transfer_via": transaction.transfer_via,
        "platform_fee": platform_fee,
        "additional_fee": transaction.additional_fee or 0,
        "date": date,
        "time": time,
        "amount": amount,
        "status": transaction.status,
        "previous_balance": transaction.previous_balance,
        "current_balance": transaction.current_balance,
        "total_amount": amount + platform_fee,
        "remark": transaction.remark or "",
    }


def generate_transfer_receipt_context(
    transaction, serialized_transaction, organization
):
    organization_details = prepare_organization_details(organization)

    purchase_request = serialized_transaction["purchase_request"]
    from_user = serialized_transaction["from_business"]["owner"]
    from_user_address = get_user_contact_details(from_user["id"])

    to_user = serialized_transaction["to_business"]["owner"]
    to_user_address = get_user_contact_details(to_user["id"])

    date, time = format_datetime(transaction.created_at)
    organization_logo_url = get_organization_logo_url(organization)

    investor_iban_number = (
        BankAccount.objects.filter(user_id=from_user["id"])
        .only("iban_code")
        .values_list("iban_code", flat=True)
        .first()
    )

    return {
        "organization_details": organization_details,
        "organization_logo_url": organization_logo_url,
        "transaction": transaction,
        "transfered_to": {
            "name": serialized_transaction["to_business"]["name"],
            "address": to_user_address["address"],
            "country": to_user_address["country"],
            "phone": to_user["phone_number"],
        },
        "transfered_from": {
            "name": serialized_transaction["from_business"]["name"],
            "address": from_user_address["address"],
            "country": from_user_address["country"],
            "phone": from_user["phone_number"],
            "iban_code": investor_iban_number or "",
        },
        "date": date,
        "time": time,
        "purchase_request": {
            "order_cost": purchase_request["order_cost"],
            "premium": purchase_request["premium"],
            "vat": purchase_request["vat"],
            "taxes": purchase_request["taxes"],
            "platform_fee": purchase_request["platform_fee"],
            "total_cost": purchase_request["total_cost"],
        },
    }
