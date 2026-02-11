from django.db.models import Value
from django.db.models.functions import Concat

from account.models import UserAssignedBusiness
from investor.models import PurchaseRequest


def base_purchase_request_queryset():
    return (
        PurchaseRequest.global_objects.select_related(
            "precious_item",
            "precious_item__created_by",
            "precious_item__precious_metal",
            "precious_item__precious_stone",
            "precious_item__material_item",
            "related_purchase_request",  # For sale requests to access related purchase request
        )
        .prefetch_related("precious_item__images")
        .annotate(
            creator_full_name=Concat(
                "created_by__first_name",
                Value(" "),
                "created_by__middle_name",
                Value(" "),
                "created_by__last_name",
            )
        )
    )


def get_business_from_user_token(request, field=None):
    """Fetch business assigned to the logged-in user."""

    current_business_id = request.auth.get("current_business")
    try:
        user_business = UserAssignedBusiness.global_objects.get(pk=current_business_id)
    except:
        return None

    if field == "business":
        return user_business.business
    elif field == "is_owner":
        return user_business.is_owner
    elif field == "business_name":
        return user_business.business.name

    else:
        return user_business
