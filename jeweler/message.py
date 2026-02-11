from django.utils.translation import gettext_lazy as _

MESSAGES = {
    # Jewelry Design Messages
    "jewelry_design_fetched": _("Jewelry designs fetched successfully."),
    "jewelry_design_created": _("Jewelry design created successfully."),
    "jewelry_design_updated": _(
        "The jewelry product has been successfully added to the collection."
    ),
    "jewelry_design_not_found": _("Jewelry design not found."),
    "single_design_product_limit": _(
        "Only single product is allowed when the design type is SINGLE."
    ),
    "jewelry_design_type_must_be_collection": _(
        "Jewelry design type must be 'COLLECTION' to add product."
    ),
    "collection_name_exists": _("Collection name already exists."),
    "jewelry_product_exists": _(
        "Product name '{product_name}' already exists for this business."
    ),
    "jewelry_product_deleted": _("Jewelry product has been deleted successfully."),
    "jewelry_product_not_found": _("Jewelry product not found."),
    "jewelry_product_fetched": _("Jewelry product fetched successfully."),
    "jewelry_design_delete_forbidden": _(
        "This collection cannot be deleted because it is assigned to a Musharakah Contract or Manufacturing Request."
    ),
    "jewelry_collection_deleted": _(
        "Jewelry collection has been deleted successfully."
    ),
    "jewelry_product_updated": _("Jewelry product has been updated successfully."),
    "collection_name_is_valid": _("Collection name is valid."),
    "collection_name_cannot_be_empty": _(
        "Collection name cannot be empty or contain only whitespace."
    ),
    "designs_added_to_collection": _(
        "Designs have been successfully added to the collection."
    ),
    "single_designs_added_to_collection": _(
        "Single designs have been successfully added to the collection."
    ),
    "cannot_add_linked_designs_to_collection": _(
        "Cannot add designs that are linked to Musharakah Contract or Manufacturing Request."
    ),
    # Musharakah Request Messages
    "business_account_not_found": _("Business account not found."),
    "risk_level_not_assigned": _("Risk level not assigned to business."),
    "musharakah_contract_request_fetched": _(
        "Musharakah contract requests fetched successfully."
    ),
    "musharakah_contract_request_created": _(
        "Musharakah contract request created successfully."
    ),
    "musharakah_contract_request_not_found": _(
        "Musharakah contract request not found."
    ),
    "musharakah_contract_terminate_request_created": _(
        "Musharakah contract termination request created successfully."
    ),
    "musharakah_contract_termination_request_exists": _(
        "Musharakah contract termination request already exists."
    ),
    "musharakah_duration_validation": _(
        "Please provide either a duration option or a custom expiry date."
    ),
    "musharakah_contract_duration_validation": _(
        "You can not craete '{duration_name}' duration musharakah contract based on your business risk level."
    ),
    "invalid_mcr_quantity_payload": _(
        "Invalid payload format. Expected a list of objects with 'id' and 'quantity'."
    ),
    "musharakah_contract_termination_request_not_found": _(
        "Musharakah contract termination request not found."
    ),
    "musharakah_contract_request_deleted": _(
        "Musharakah Contract Request deleted successfully."
    ),
    "delete_musharakah_contract_request_failed_investor_assigned": _(
        "You cannot delete this Musharakah contract request because an investor has already invested in it."
    ),
    "musharakah_contract_statistics_retrieved": _(
        "Musharakah contract statistics retrieved successfully."
    ),
    "musharakah_contract_request_quantity_updated": _(
        "Musharakah contract request quantity updated successfully."
    ),
    "musharakah_contract_request_quantity_not_found": _(
        "Musharakah contract request quantity not found."
    ),
    "musharakah_contract_active_can_not_update": _(
        "The Musharakah contract is active and cannot be updated."
    ),
    "quantity_should_not_be_zero": _("Quantity must be greater than zero."),
    "musharakah_contract_not_created_yet": _(
        "The Musharakah contract has not been created yet with any investor."
    ),
    "musharakah_contract_pending_for_approval": _(
        "The Musharakah contract has not been approved yet by the admin."
    ),
    "musharakah_contract_agreement_posted": _(
        "Musharakah contract agreement posted successfully."
    ),
    "jewelry_design_cannot_have_multiple_musharakah_contract_requests": _(
        "This jewelry design is already linked to a Musharakah contract request and cannot be assigned to another."
    ),
    "jewelry_production_inspection_must_by_admin_approved": _(
        "The jewelry production must be approved by the admin inspection before proceeding."
    ),
    "jewelry_production_payment_already_completed": _(
        "The payment for this jewelry production has already been proceed."
    ),
    "production_payment_asset_allocation_required": _(
        "Asset allocation is required for production payment when the payment type is '{payment_type}'."
    ),
    # Fetching purchase requests and related asset contributions
    "jeweler_assets_fetched": _(
        "Purchase requests and asset contributions from investors fetched successfully."
    ),
    # Dashboard messages
    "dashboard_insights_fetched": _("Dashboard insights fetched successfully."),
    # muanufacturing request messages
    "manufacturer_business_account_fetched": _(
        "Manufacturer business accounts fetched successfully."
    ),
    "manufacturing_request_fetched": _("Manufacturing requests fetched successfully."),
    "manufacturing_request_created": _("Manufacturing request created successfully."),
    "manufacturing_request_not_found": _("Manufacturing request not found."),
    "manufacturing_estimation_request_not_found": _(
        "Manufacturing estimation request not found."
    ),
    "manufacturing_estimation_request_approved": _(
        "Manufacturing estimation request has been approved."
    ),
    "manufacturing_estimation_request_rejected": _(
        "Manufacturing estimation request has been rejected."
    ),
    "manufacturing_request_must_be_pending": _(
        "The manufacturing request must be in a pending status to approve or reject the estimation."
    ),
    "manufacturing_request_payment_created": _(
        "The payment for manufacturing request has been successfully processed."
    ),
    "manufacturing_request_paymet_already_completed": _(
        "The payment for this manufacturing request has already been completed."
    ),
    "manufacturing_estimation_request_mismatch": _(
        "The estimation request does not belong to this manufacturing request."
    ),
    "manufacturing_estimation_request_not_accepted": _(
        "Payment can only be made for accepted estimation requests."
    ),
    "correction_amount_added": _("Corection amount added successfully."),
    "production_payment_success": _(
        "The payment for jewelry production has been successfully processed."
    ),
    "insufficient_contribution_for_material": _(
        "Insufficient assets to meet the required material for jewelry production."
    ),
    "invalid_material_type": _("Invalid material type found in asset contribution."),
    "jewelry_product_delete_forbidden": _(
        "This product cannot be deleted because it is assigned to a Musharakah Contract or Manufacturing Request."
    ),
    "jewelry_product_update_forbidden": _(
        "This product cannot be updated because it is assigned to a Musharakah Contract or Manufacturing Request."
    ),
    "manufacturing_estimation_request_already_processed": "Manufacturing estimation request is already {status}.",
    "quantity_required_for_shape_cut": _(
        "Quantity is required when shape cut is provided."
    ),
    # Limitation messages based on subscription plan
    "free_trial_musharakah_weight_limit": _(
        "Plan limitation: Maximum musharakah request weight is {max_weight}g, but you requested {requested_weight}g."
    ),
    "free_trial_metal_purchase_weight_limit": _(
        "Plan limitation: Maximum metal purchase weight is {max_weight}g, but you are trying to purchase {purchase_weight}g."
    ),
    "free_trial_jeweler_design_limit": _(
        "Plan limitation: Maximum number of designs is {max_designs}, but you already have {current_design_count} designs."
    ),
    "free_trial_musharakah_total_weight_limit": _(
        "Plan limitation: Maximum total musharakah weight is {max_weight}g. You currently have {existing_weight}g in active contracts and are requesting {requested_weight}g, which would total {total_weight}g and exceed your limit."
    ),
    "musharakah_single_request_weight_limit": _(
        "Musharakah request weight limit: Maximum musharakah request weight per request is {max_weight}g, but you requested {requested_weight}g."
    ),
    "termination_request_by_investor": _(
        "Settlement payment cannot be processed because the termination request was initiated by the Investor."
    ),
    "settlement_payment_already_processed": _(
        "musharakah contract payment is already settled."
    ),
    "termination_request_by_jeweler": _(
        "Settlement payment cannot be processed because the termination request was initiated by the Jeweler."
    ),
    "musharakah_contract_manufacturing_cost_retrieved": _(
        "Manufacturing cost retrieved successfully."
    ),
    "assets_required_for_asset_payment": _(
        "Assets are required for asset payment type."
    ),
    "asset_quantity_must_be_greater_than_zero": _(
        "Asset at index {index}: Quantity must be greater than 0."
    ),
    "asset_serial_numbers_quantity_mismatch": _(
        "Asset at index {index}: Number of serial numbers ({serial_count}) must match quantity ({quantity})."
    ),
    "total_serial_numbers_quantity_mismatch": _(
        "Total serial numbers ({serial_count}) must match total quantity ({quantity})."
    ),
    "invalid_purchase_request": _("Invalid purchase request provided."),
    "invalid_precious_item_unit": _(
        "Invalid precious item units or serial numbers: {units}. Please ensure they exist and belong to the specified purchase request."
    ),
    "precious_item_unit_purchase_request_mismatch": _(
        "Precious item units {units} do not belong to purchase request {purchase_request_id}."
    ),
    "inventory_dashboard_statistics": _(
        "Inventory dashboard statistics fetched successfully."
    ),
    "inventory_dashboard_list_fetched_successfully": _(
        "Inventory stock list fetched successfully."
    ),
    "inventory_stock_details_fetched_successfully": _(
        "Inventory stock details fetched successfully."
    ),
    "marketplace_product_list_fetched_successfully": _(
        "Marketplace products list fetched successfully."
    ),
    "jewelry_sales_list_fetched_successfully": _(
        "Jewelry sales list fetched successfully."
    ),
    "jewelry_sales_details_fetched_successfully": _(
        "Jewelry sales details fetched successfully."
    ),
    "inventory_general_insights_fetched_successfully": _(
        "Inventory general insights fetched successfully."
    ),
}
