from django.utils.translation import gettext_lazy as _

MESSAGES = {
    "metal_created": _("Precious Metal created successfully."),
    "metal_updated": _("Precious Metal updated successfully."),
    "metal_deleted": _("Precious Metal deleted successfully."),
    "metal_retrieved": _("Precious Metal retrieved successfully."),
    "metals_retrieved": _("Precious Metals retrieved successfully."),
    "metal_fetched": _("List of Precious Metal fetched successfully."),
    "stone_created": _("Precious Stone created successfully."),
    "stone_updated": _("Precious Stone updated successfully."),
    "stone_deleted": _("Precious Stone deleted successfully."),
    "stone_retrieved": _("Precious Stone retrieved successfully."),
    "stones_retrieved": _("Precious Stones retrieved successfully."),
    "stone_fetched": _("List of Precious Stone fetched successfully."),
    "purchase_request_updated": _("Purchase request status updated successfully."),
    "purchase_request_fetched": _("Purchase request fetched successfully."),
    "precious_metal_item_created": _("Precious Item created successfully!"),
    "precious_item_updated": _("Precious Item updated successfully!"),
    "precious_item_deleted": _("Precious Item deleted successfully!"),
    "precious_item_not_found": _("Precious Item not found."),
    "precious_item_fetched": _("Precious Items fetched successfully."),
    "premium_price_amount_required_error": _("Premium price amount is required "),
    "premium_price_rate_required_error": _("Premium price rate is required "),
    "premium_price_amount_percentage_required_error": _(
        "Premium price percentage and amount is required."
    ),
    "sales_by_continent_fetched": _("Sales by continent fetched successfully."),
    "business_inactive": _(
        "The business associated with this purchase request is no longer active."
    ),
    "carat_type_required": _("Carat type is required."),
    "carat_type_not_found": _("Carat type not found."),
    "stone_shape_cut_not_found": _("Stone shape/cut not found."),
    "stone_shape_cut_required": _("Stone shape/cut is required."),
    "purchase_request_status_must_be_pending": _(
        "Purchase request status must be 'Pending' in order to approve or reject it."
    ),
    "report_number_exist": _("Report number already exists."),
    "report_number_is_valid": _("Report number is valid."),
    "precious_item_disabled": _(
        "Precious item has been disabled as it is linked to existing purchases."
    ),
    "invalid_serial_number_format": _(
        "Invalid serial number format: expected a list of serial numbers (e.g. ['A0001', 'A0002'])."
    ),
    "serial_number_quantity_mismatch": _(
        "The number of serial numbers must match the total quantity of items requested."
    ),
    "serial_number_already_exist": _(
        "The following serial numbers are already used: {serial_numbers}. Please provide unique serial numbers."
    ),
    "serial_number_validation": _(
        "Duplicate serial numbers found in request. Please ensure all are unique."
    ),
    "serial_number_required": _(
        "Serial numbers are required to approve a purchase request."
    ),
    "serial_number_not_found_or_unavailable": _(
        "These serial numbers are not found or not available for sale: {serial_numbers}. Please verify that they are correct and not already sold or allocated."
    ),
}
