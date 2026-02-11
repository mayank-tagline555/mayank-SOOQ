from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import DecimalField
from django.db.models import ExpressionWrapper
from django.db.models import F
from django.db.models import Q
from django.db.models import Sum
from django.db.models import Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from account.models import FCMToken
from sooq_althahab.enums.investor import PurchaseRequestStatus
from sooq_althahab.enums.investor import RequestType
from sooq_althahab.enums.sooq_althahab_admin import MaterialType
from sooq_althahab_admin.models import MaterialItem


def get_fcm_tokens_for_users(user_ids):
    """
    Filters and retrieves FCM tokens for the given list of user IDs.
    Args:
        user_ids: A list of user IDs.
    Returns:
        A list of FCM tokens (excluding null/empty tokens).
    """
    if not user_ids:
        return []

    fcm_tokens = (
        FCMToken.objects.filter(user_id__in=user_ids, fcm_token__isnull=False)
        .exclude(fcm_token="")
        .values_list("fcm_token", flat=True)
        .distinct()
    )
    return list(fcm_tokens)


def get_custom_time_range():
    # As per frontend requirements, we are using 1Y, 3Y, and 5Y
    # return all the data for this period with API response

    now = timezone.now()

    # Start date of current month
    current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Dates of last month
    last_month_end = current_month_start - timedelta(seconds=1)
    last_month_start = last_month_end.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )

    return {
        "ALL": None,
        "1Y": now - timedelta(days=365),
        "3Y": now - timedelta(days=3 * 365),
        "5Y": now - timedelta(days=5 * 365),
        "CURRENT_MONTH": current_month_start,
        "LAST_MONTH": (last_month_start, last_month_end),
    }


def get_sales_data(purchase_requests, completed_requests, start_date, business):
    """
    Helper function to fetch sales data from a specific date onward.

    Args:
        purchase_requests (QuerySet): Purchase requests related to the logged-in seller.
        completed_requests (QuerySet): Completed purchase requests.
        start_date (datetime): The start date for filtering sales data.

    Returns:
        dict: Aggregated sales data for the given period.
    """

    # As per frontend requirements, we are using 1Y, 3Y, and 5Y
    # return all the data for this period with API response
    time_ranges = get_custom_time_range()

    # Calculate total_sales per time range
    total_sales = {}

    # Compute total sales for ALL, 1Y, 3Y, 5Y
    for label, time_range in time_ranges.items():
        if label == "ALL":
            filtered_requests = completed_requests
        elif label == "LAST_MONTH":
            start, end = time_range
            filtered_requests = completed_requests.filter(
                created_at__range=(start, end)
            )
        else:
            filtered_requests = completed_requests.filter(created_at__gte=time_range)

        total = filtered_requests.aggregate(
            total=Coalesce(Sum("premium"), Value(0), output_field=DecimalField())
        )["total"]
        total_sales[label] = round(total or 0, 2)

    # Purchase requests of type PURCHASE
    asset_purchase_requests = purchase_requests.filter(
        request_type=RequestType.PURCHASE
    )

    # Metal quantity sold
    total_metal_quantity_sold = completed_requests.filter(
        precious_item__material_type=MaterialType.METAL
    ).aggregate(
        total=Coalesce(
            Sum(F("requested_quantity") * F("precious_item__precious_metal__weight")),
            Value(0),
            output_field=DecimalField(max_digits=12, decimal_places=4),
        )
    )[
        "total"
    ]

    total_metal_quantity_sold = str(round(total_metal_quantity_sold or 0, 2))

    # Sales grouped by material
    sales_by_material = defaultdict(lambda: Decimal("0.00"))
    for request in completed_requests:
        name = request.precious_item.material_item.name
        sales_by_material[name] += request.order_cost + request.premium

    sales_by_material_list = [
        {"name": name, "total_sales": str(round(amount, 2))}
        for name, amount in sales_by_material.items()
    ]

    # Role-wise stats
    roles = ["INVESTOR", "JEWELER"]
    purchase_request_counts_data = {}

    for role in roles:
        role_wise_requests = asset_purchase_requests.filter(
            business__business_account_type=role
        )
        role_sales_requests = role_wise_requests.filter(
            request_type=RequestType.SALE, status=PurchaseRequestStatus.PENDING
        )

        purchase_request_counts_data[role] = {
            "total_purchase_requests_count": role_wise_requests.count(),
            "sales_requests_count": role_sales_requests.count(),
            "pending_purchase_requests_count": role_wise_requests.filter(
                status=PurchaseRequestStatus.PENDING
            ).count(),
            "unallocated_purchase_request_count": role_wise_requests.filter(
                status=PurchaseRequestStatus.APPROVED
            ).count(),
            "completed_purchase_requests_count": role_wise_requests.filter(
                status=PurchaseRequestStatus.COMPLETED
            ).count(),
            # TODO allocated count based on which assets are allocated in the musharakah or pools
            # we need to set it after the musharakah or pools are created
            "allocated_purchase_request_count": 0,
        }

    return {
        "total_sales": total_sales,
        "total_metal_quantity_sold": total_metal_quantity_sold,
        "sales_by_material": sales_by_material_list,
        "purchase_request_counts": purchase_request_counts_data,
    }
