from django.utils.translation import gettext_lazy as _

MESSAGES = {
    "manufacturing_request_estimation_created": _(
        "Manufacturing request estimation created successfully."
    ),
    "jewelry_production_fetched": _("Jewelry production fetched successfully."),
    "jewelry_production_not_found": _("Jewelry production not found."),
    "jewelry_production_invalid_status_change": _(
        "The Jewelry production status from '{current}' to '{new}' is not permitted."
    ),
    "delivery_date_error": _("The delivery date must be set to a future date."),
    "jewelry_production_status_updated": _(
        "The jewelry production status has been updated successfully."
    ),
    "jewelry_production_delivery_date_updated": _(
        "The jewelry production delivery date has been updated successfully."
    ),
    "jewelry_product_invalid_status_change": _(
        "The jewelry product status from '{current}' to '{new}' is not permitted."
    ),
    "jewelry_product_status_updated": _(
        "The jewelry product status has been updated successfully."
    ),
    "jewelry_product_not_found": _("Jewelry product not found."),
    "jewelry_inspection_status_must_be_pending_payment": _(
        "Inspection status must be 'Payment Pending' to add correction amount."
    ),
    "dashboard_data_fetched": _("Dashboard data fetched successfully."),
    "stone_price_added": _("Stone price added successfully."),
    "jeweler_status_already_updated": _(
        "The jeweler has already updated the inspection status for this production."
    ),
    "jewelry_production_inspection_in_progress": _(
        "Jewelry production inspection is currently in progress. Please wait until it is completed."
    ),
    "correction_value_payment_already_completed": _(
        "Cannot add correction value. The manufacturing payment has already been completed for this jewelry production."
    ),
}
