from django.utils.translation import gettext_lazy as _

MESSAGES = {
    "products_retrieved": _("Products retrieved successfully."),
    "product_retrieved": _("Product retrieved successfully."),
    "realized_profit_retrieved": _("Realized profit retrieved successfully."),
    "product_type_missing": _("Product type is required (either 'Stone' or 'Metal')."),
    "invalid_product_type": _("Invalid product type. Must be 'Stone' or 'Metal'."),
    "product_not_found": _("Product not found."),
    "something_wrong": _("Something went wrong. Please try again later."),
    "purchase_request_created": _("Purchase request created successfully."),
    "purchase_request_created_and_assigned_precious_item": _(
        "Purchase request created and precious item assigned successfully."
    ),
    "purchase_request_retrieved": _("Purchase requests retrieved successfully."),
    "server_error": _("Internal server error. Please contact support."),
    "exceeds_available_quantity": _(
        "Requested quantity exceeds the available quantity from the original purchase (only {quantity} remaining)."
    ),
    "purchase_request_empty": _("No purchase requests found."),
    "material_items_retrieved": _("Material items retrieved successfully."),
    "purchase_request_fetched": _("Purchase requests fetched successfully."),
    "portfolio_history_fetched": _("Portfolio history fetched successfully."),
    "wallet_not_found": _("Wallet not found."),
    "wallet_balance_retrieved": _("Your total available balance."),
    "invalid_amount": _("Invalid amount format."),
    "amount_required": _("Amount is required."),
    "amount_positive": _("Amount must be greater than zero."),
    "deposit_request_created": _("Amount deposit request created successfully."),
    "withdraw_request_created": _("Amount withdraw request created successfully."),
    "insufficient_balance": _("Insufficient balance."),
    "invalid_transaction_type": _("Invalid transaction type."),
    "transaction_not_found": _("Transaction not found."),
    "transactions_fetched": _("Transactions fetched successfully."),
    "transaction_retrieved": _("Transaction details retrieved successfully."),
    "invalid_wallet": _("Wallet not found for the business."),
    "precious_item_required": _("Precious item is required."),
    "precious_item_out_of_stock": _("The selected precious item is out of stock."),
    "purchase_request_not_found": _("Purchase request not found."),
    "business_account_not_found": _("Business account not found."),
    "purchased_assets_statistics_retrieved": _(
        "Purchase request statistics and material summary have been successfully retrieved."
    ),
    "transaction_type_invalid": _(
        "The selected transaction type is not valid for PDF generation."
    ),
    "transaction_receipt_mailed": _(
        "The transaction receipt has been successfully sent via email."
    ),
    "invalid_email": _("The user does not have a valid email address."),
    # Filterd purchase request for musharakah and pools
    "invalid_json_format": _("The 'filters' parameter must be valid JSON."),
    "filter_value_validation": _(
        "The 'filters' parameter must be a list of dictionaries."
    ),
    # Sales request
    "price_locked_required": _("The price locked value is required."),
    "sale_request_created": _("Sale request created successfully."),
    "purchase_request_not_eligible_for_sale": _(
        "Only purchase requests with an Approved or Completed status are eligible for sale."
    ),
    "purchase_request_item_already_sold": _(
        "This precious item has already been sold."
    ),
    "sale_request_already_created": _(
        "A sale request has already been created for this purchase request."
    ),
    "sale_request_approved": _("Sale request approved successfully."),
    "sale_request_rejected": _("Sale request rejected successfully."),
    "search_results_not_found": _(
        "No search results found for the given material item."
    ),
    "attachments_required": _("Attachments are required."),
    "purchase_request_deleted": _("Purchase request deleted successfully."),
    "invalid_requested_quantity": _("Requested quantity must be greater than zero."),
    "seller_business_inactive_for_sale_request": _(
        "Sale requests cannot be processed as the seller is no longer active."
    ),
    # Asset contribution model
    "pool_required": _("'pool' is required when the contribution_type is 'POOL'."),
    "musharakah_contract_request_required": _(
        "'musharakah_contract_request' is required when the contribution_type is 'MUSHARAKAH'."
    ),
    "asset_contributed_in_pool": _(
        "You've successfully invested in the pool using your asset."
    ),
    "asset_contribution_required": _(
        "Please select your assets to proceed with the contribution."
    ),
    "pool_target_achieved": _(
        "The pool has met its target weight and can no longer accept additional contributions."
    ),
    "musharakah_contract_request_already_investor_assigned": _(
        "The investor has already been assigned to a Musharakah Contract Request."
    ),
    "asset_not_enough_in_pool": _("Insufficient assets to meet the pool requirements."),
    "assets_not_enough_in_musharakah_conract_request": _(
        "Insufficient assets to meet the Musharakah Contract Request requirements."
    ),
    "asset_contributed_in_musharakah_contract_request": _(
        "Your asset has been successfully invested in the Musharakah Contract Request."
    ),
    "selected_asset_contribution_exceeds_required_weight": _(
        "The asset weight exceeds the required limit for this material."
    ),
    "asset_contribution_material_mismatch": _(
        "The contributed asset does not match any of the required materials."
    ),
    "quantity_must_be_greater_zero": _("Quantity must be greater than zero."),
    "musharakah_contract_request_summary_retrieved": _(
        "Musharakah contract request summary retrieved successfully."
    ),
    "pool_summary_retrieved": _("Pool summary retrieved successfully."),
    "asset_contribution_fetched": _(
        "Asset contributions (allocated assets) retrieved successfully."
    ),
    "production_payment_required": _(
        "Production payment is required to proceed with the asset contribution."
    ),
    # Serial number validation messages
    "serial_number_already_exist": _(
        "The following serial numbers are already used: {serial_numbers}. Please provide unique serial numbers."
    ),
    "system_serial_number_already_exist": _(
        "The following system serial numbers are already used: {system_serial_numbers}. Please provide unique system serial numbers."
    ),
    "termination_fee_processed_successfully": _(
        "Termination fee processed successfully."
    ),
    "logistic_cost_payable_by_jeweler": _(
        "Logistic cost payment cannot be processed because the logistics cost is payable by the Jeweler."
    ),
    "logistic_cost_payment_already_processed": _(
        "Logistic cost payment is already processed."
    ),
    "sooq_al_thahab_has_not_added_refining_cost": _(
        "The Sooq Al Thahab has not added the refining cost yet."
    ),
    "refining_cost_processed_successfully": _("Refining cost processed successfully."),
    "musharakah_contract_agreement_retrieved": _(
        "Musharakah contract agreement details retrieved successfully."
    ),
    "manufacturing_cost_payment_option_not_selected": _(
        "The cost payment option has not been selected by Sooq Al Thahab for this termination request."
    ),
    "early_termination_fee_payment_already_processed": _(
        "Musharakah contract early termination payment is already processed."
    ),
    "admin_asset_purchase_not_allowed": _(
        "This asset cannot be purchased as it belongs to the admin account."
    ),
    "subscription_feature_access_denied": _(
        "Your subscription doesn't have this feature access. To use {feature_name}, you need to update your subscription plan."
    ),
    "musharakah_contract_profit_retrieved": _(
        "Musharakah contract profit retrieved successfully."
    ),
    "serial_number_exists": _("Serial number already exists in this purchase request."),
    "serial_number_unique": _("Serial number is unique."),
    "system_serial_number_exists": _("System serial number is already allocated."),
    "system_serial_number_unique": _("System serial number is unique."),
    "invalid_serial_validation_request": _(
        "Provide either serial_number or system_serial_number."
    ),
    "purchase_request_id_required": _(
        "purchase_request_id is required when checking serial_number."
    ),
}
