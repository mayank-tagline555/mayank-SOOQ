from django.utils.translation import gettext_lazy as _

MESSAGES = {
    # Common messages
    "error": _("Something went wrong. Please try again."),
    # Sub admin registration messages
    "sub_admin_created": _("Sub admin created successfully!"),
    "sub_admin_already_exists_with_role": _("Sub admin with this role already exists."),
    "invalid_role": _("Please select the valid role for the user."),
    "user_not_found": _("User not found."),
    "sub_admin_deleted": _("Sub admin deleted successfully."),
    "user_updated": _("User updated successfully!"),
    "user_not_sub_admin": _("User is not sub admin."),
    "material_item_already_exists": _("A Material item already exists."),
    "material_item_created": _("Material Item created successfully."),
    "users_listed": _("Users listed successfully."),
    "global_metal_required": _(
        "This field is required when the material type is metal."
    ),
    "sub_admin_list": _("Sub admin list fetched successfully."),
    "sub_admin_detail": _("Sub admin details fetched successfully."),
    "users_details_fetched": _("User details fetched successfully."),
    "validate_for_the_existing_users_in_the_business": _(
        "Deletion blocked: This business has {assigned_users_count} assigned users. Please remove all other assigned users before deleting."
    ),
    "business_and_associate_record_are_deleted": _(
        "Business and all associated records have been permanently deleted."
    ),
    "business_has_subscription_plan": _(
        "Deletion blocked: This business has an active or free subscription."
    ),
    "purchase_request_fetched": _("Purchase requests fetched successfully."),
    "purchase_request_retrieved": _("Purchase requests retrieved successfully."),
    "material_items_retrieved": _("Material items retrieved successfully."),
    "organization_taxes_and_fees_updated": _(
        "Organization taxes and fees updated successfully."
    ),
    "material_item_not_found": _("Material item not found."),
    "material_item_updated": _("Material item updated successfully."),
    "organization_currencies_fetched": _(
        "Organization currencies fetched successfully."
    ),
    "organization_currency_created": _("Organization currency created successfully."),
    "organization_currency_not_found": _("Organization currency not found."),
    "invalid_rate": _("Rate must be greater than zero."),
    "organization_currency_update": _("Organization currency updated successfully."),
    "transaction_not_found": _("Transaction not found."),
    "transactions_fetched": _("Transactions fetched successfully."),
    "subscription_transactions_fetched": _(
        "Subscription transactions fetched successfully."
    ),
    "transaction_retrieved": _("Transaction details retrieved successfully."),
    "restrict_to_update_transaction": _(
        "Unable to update transaction: associated user account has been deleted."
    ),
    "only_stone_creation_allowed": _(
        "Only stone can be created. Adding new metals is not allowed."
    ),
    "organization_details_fetched": _("Organization details fetched successfully."),
    "platform_fee_rate_required": _(
        "Platform fee rate is required when fee type is set to percentage."
    ),
    "invalid_platform_fee_amount": _(
        "Platform fee amount must be 0 or null when fee type is set to percentage."
    ),
    "platform_fee_amount_required": _(
        "Platform fee amount is required when fee type is set to amount."
    ),
    "invalid_platform_fee_rate": _(
        "Platform fee rate must be 0 or null when fee type is set to amount."
    ),
    "purchase_request_status_completed": _("Purchase request completed successfully."),
    "purchase_request_approved_error": _(
        "Purchase request must be APPROVED to complete the request."
    ),
    "purchase_request_already_completed": _(
        "Purchase request has already been completed."
    ),
    "purchase_request_already_completed": _(
        "Purchase request has already been completed."
    ),
    "withdraw_request_accepted": _("Withdraw request accepted successfully."),
    "withdraw_request_rejected": _("Withdraw request rejected successfully."),
    "deposit_request_accepted": _("Deposit request accepted successfully."),
    "deposit_request_rejected": _("Deposit request rejected successfully."),
    "currency_code_already_exists": _("Currency code already exists."),
    "user_reactivated": _("User has been reactivated successfully."),
    "user_suspended": _("User has been suspended successfully."),
    "organization_bank_account_created": _(
        "Organization bank account created successfully."
    ),
    "organization_bank_account_updated": _(
        "Organization bank account updated successfully."
    ),
    "organization_bank_account_fetched": _(
        "Organization bank account fetched successfully."
    ),
    "organization_bank_account_not_found": _("Organization bank account not found."),
    "organization_bank_account_already_exists": _(
        "Organization bank account already exists."
    ),
    "business_account_suspended": _(
        "Business account has been suspended successfully."
    ),
    "business_account_reactivated": _(
        "Business account has been reactivated successfully."
    ),
    "business_subscription_details_fetched": _(
        "Business subscription details fetched successfully."
    ),
    "business_subscription_not_found": _("Business subscription not found."),
    "risk_level_update_allowed_for_jeweler_only": _(
        "Risk level can only be updated for jeweler businesses."
    ),
    "business_risk_level_updated": _("Business risk level updated successfully."),
    # Stone cut shape messages
    "stone_cut_shape_created": _("Stone cut shape created successfully."),
    "stone_cut_shape_updated": _("Stone cut shape updated successfully."),
    "stone_cut_shape_not_found": _("Stone cut shape not found."),
    "stone_cut_shape_exists": _("Stone cut shape already exists."),
    "stone_cut_shape_fetched": _("Stone cut shape fetched successfully."),
    # Stone clarity messages
    "stone_clarity_created": _("Stone clarity created successfully."),
    "stone_clarity_updated": _("Stone clarity updated successfully."),
    "stone_clarity_not_found": _("Stone clarity not found."),
    "stone_clarity_fetched": _("Stone clarity fetched successfully."),
    # Metal carat type messages
    "metal_carat_type_exists": _("Metal carat type already exists."),
    "metal_carat_type_created": _("Metal carat type created successfully."),
    "metal_carat_type_updated": _("Metal carat type updated successfully."),
    "metal_carat_type_not_found": _("Metal carat type not found."),
    "metal_carat_type_fetched": _("Metal carat type fetched successfully."),
    # Pool messages
    "pool_fetched": _("Pool fetched successfully."),
    "pool_created": _("Pool created successfully."),
    "material_item_required": _("Material item is required."),
    "stone_cut_shape_required": _("Stone cut shape is required."),
    "metal_carat_type_required": _("Metal carat type is required."),
    "pool_not_found": _("Pool not found."),
    "pool_updated": _("Pool updated successfully."),
    # Jewelry product type messages
    "jewelry_product_type_created": _("Jewelry product type created successfully."),
    "jewelry_product_type_fetched": _("Jewelry product type fetched successfully."),
    "jewelry_product_type_exists": _("Jewelry product type already exists."),
    "jewelry_product_type_not_found": _("Jewelry product type not found."),
    "jewelry_product_type_updated": _("Jewelry product type updated successfully."),
    # Jewelry product color messages
    "jewelry_product_color_created": _("Jewelry product color created successfully."),
    "jewelry_product_color_fetched": _("Jewelry product color fetched successfully."),
    "jewelry_product_color_exists": _("Jewelry product  color already exists."),
    "jewelry_product_color_not_found": _("Jewelry product color not found."),
    "jewelry_product_color_updated": _("Jewelry product color updated successfully."),
    # Musharakah contract request messages
    "musharakah_contract_request_already_terminated": _(
        "Musharakah contract request already terminated."
    ),
    "musharakah_contract_request_already_completed": _(
        "Musharakah contract request already completed."
    ),
    "musharakah_contract_request_already_approved": _(
        "Musharakah contract request already approved."
    ),
    "musharakah_contract_request_already_rejected": _(
        "Musharakah contract request already rejected."
    ),
    "musharakah_contract_request_investor_not_assigned": _(
        "No investor has been assigned to the Musharakah contract request."
    ),
    "musharakah_contract_request_approved": _(
        "Musharakah contract request approved successfully."
    ),
    "musharakah_contract_request_rejected": _(
        "Musharakah contract request rejected successfully."
    ),
    "musharakah_contract_request_terminated": _(
        "Musharakah contract request terminated successfully."
    ),
    "musharakah_contract_request_inactive": _(
        "Musharakah contract request must be active in order to terminate it."
    ),
    "musharakah_contract_request_must_be_approved": _(
        "Musharakah contract request must be approved in order to terminate it."
    ),
    "musharakah_contract_request_already_handled": _(
        "Musharakah contract request has already been approved or rejected."
    ),
    "musharakah_contract_termination_request_fetched": _(
        "Musharakah contract termination request fetched successfully."
    ),
    "musharakah_contract_renewed": _(
        "Musharakah contract has been renewed successfully.",
    ),
    "musharakah_contract_request_not_active": _(
        "Musharakah contract request must be active in order to renew it."
    ),
    "musharakah_contract_request_not_approved": _(
        "Musharakah contract request must be approved in order to renew it."
    ),
    # Musharakah contract duration choices messages
    "musharakah_duration_created": _("Musharakah duration created successfully."),
    "musharakah_duration_fetched": _(
        "Musharakah duration fetched successfully.",
    ),
    "musharakah_duration_updated": _("Musharakah duration updated successfully."),
    "musharakah_duration_not_found": _("Musharakah duration not found."),
    "same_name_validation": _("A duration choice with this name already exists."),
    "pool_creation_denied_investor_already_asssigned_in_musharakah_contract_request": _(
        "Investor already assigned to the Musharakah contract request, can't create pool."
    ),
    "jewelry_inspection_status_updated": _(
        "The jewelry inspection status has been updated successfully."
    ),
    "jewelry_production_inspection_invalid_status_change": _(
        "The jewelry production inspection status from '{current}' to '{new}' is not permitted."
    ),
    "jewelry_product_inspection_status_updated": _(
        "The jewelry product inspection status has been updated successfully."
    ),
    "jewelry_product_inspection_status_must_be_pending": _(
        "The jewelry product inspection status must be pending to update the status."
    ),
    "pool_contributor_approved": _("Pool contributor has been approved successfully."),
    "pool_contributor_rejected": _("Pool contributor has been rejected successfully."),
    "jewelry_production_payment_not_completed": _(
        "Jewelry production payment must be completed before updating the delivery status."
    ),
    "jewelry_products_delivery_status_updated": _(
        "Jewelry products delivery status has been updated successfully."
    ),
    "jewelry_products_same_delivery_status": _(
        "The jewelry products delivery status is already set to '{status}'."
    ),
    "jewelry_products_invalid_delivery_status_change": _(
        "The jewelry products delivery status cannot be changed from '{current}' to '{new}'."
    ),
    "jewelry_product_comment_added": _("Comment added successfully."),
    # Rike level messahes
    "risk_levels_fetched": _("Risk levels fetched successfully."),
    "risk_level_retrieved": _("Risk levels retrieved successfully."),
    "risk_level_created": _("Risk level created successfully."),
    "risk_level_updated": _("Risk level updated successfully."),
    "duplicate_risk_level_validation": _(
        "Risk level '{risk_level}' already exists for your organization."
    ),
    "risk_level_required": _("Risk level is required for creating a pool."),
    "invalid_risk_level": _("Please select a valid risk level for the pool."),
    "required_risk_level_for_duration": _(
        "Please select at least one risk level for this duration. This field is required and cannot be empty."
    ),
    "validate_equity_min_for_risk_level": _(
        "A risk level with this equity_min already exists for your organization."
    ),
    "validate_equity_min_max_for_risk_level": _(
        "Equity min must be less than equity max for the risk level."
    ),
    # Taqabeth messages
    "taqabeth_dashboard_data_fetched": _(
        "Taqabeth dashboard data fetched successfully."
    ),
    "taqabeth_request_fetched": _("Taqabeth request fetched successfully."),
    "occupied_stock_fetched": _("Occupied stock fetched successfully."),
    "invalid_date_range": _(
        "Invalid date range. 'Created From' must be earlier than 'Created To'."
    ),
    "occupied_stock_not_found": _("Occupied stock not found."),
    "stone_clarity_exists": _("Stone clarity already exists."),
    "investor_business_listed": _("Investor business list retrieved successfully."),
    "storage_box_number_required": _("Storage box number is required."),
    "storage_box_number_updated": _("Storage box number updated successfully."),
    "storage_box_number_or_units_required": _(
        "Provide either storage_box_number or units to update."
    ),
    "precious_item_units_and_box_number_updated": _(
        "Precious item units and box number updated successfully."
    ),
    "precious_item_units_required": _("Precious item units are required."),
    "precious_item_units_count_mismatch": _(
        "Precious item unit count ({provided_count}) does not align with contributed asset quantity ({total_contributed_quantity})."
    ),
    "precious_item_units_fetched": _("Precious item units fetched successfully."),
    "system_serial_number_validation": _(
        "Duplicate system serial numbers found in request. Please ensure all are unique."
    ),
    "no_pending_termination_request_found": _(
        "No pending termination request found for the specified Musharakah contract."
    ),
    "impacted_party_required": _("Impacted party field is required."),
    "termination_request_updated": _("Termination request updated successfully."),
    "musharakah_contract_termination_request_already_exists": _(
        "Termination request for this Musharakah contract is already in progress."
    ),
    "system_serial_number_updated": _("System serial numbers updated successfully."),
    "missing_precious_item_units_id": _(
        "The following PreciousItemUnit ID(s) were not found: ({missing_ids})"
    ),
    "already_approved": _("Contributor has been already approved."),
    "already_rejected": _("Contributor has been already rejected."),
    "serial_number_added": _(
        "Serial number of given asset has been successfully added"
    ),
    "fund_status_updated": _("Fund status has been updated successfully."),
    # Business list messages
    "business_list_retrieved": _("Business list retrieved successfully."),
    # Data fetched messages
    "data_fetched": _("Data fetched successfully."),
    # Business owner messages
    "business_owners_not_found": _(
        "Business owner(s) not found for this Musharakah contract."
    ),
    # Subscription plan messages
    "subscription_plan_created": _("Subscription plan created successfully."),
    "subscription_plans_retrieved": _("Subscription plans retrieved successfully."),
    "subscription_plan_not_found": _("Subscription plan not found."),
    "subscription_plan_retrieved": _("Subscription plan retrieved successfully."),
    "subscription_plan_updated": _("Subscription plan updated successfully."),
    "subscription_plan_linked_to_subscriptions": _(
        "Subscription plan is linked to existing subscriptions and cannot be deleted."
    ),
    "subscription_plan_deleted": _("Subscription plan deleted successfully."),
    "missing_field_is_active": _("Missing field 'is_active'."),
    "subscription_plan_activation_status_updated": _(
        "Subscription plan activation status updated."
    ),
    # Business subscription management messages
    "business_subscription_auto_renewal_disabled": _(
        "Business subscription auto-renewal disabled successfully."
    ),
    "business_subscription_suspended": _(
        "Business subscription suspended successfully."
    ),
    "business_subscription_plan_updated": _(
        "Business subscription plan updated successfully."
    ),
    "stock_list_fetched_successfully": _("Stock list fetched successfully."),
    "stock_details_fetched_successfully": _("Stock details fetched successfully."),
    "stock_details_updated_successfully": _("Stock details updated successfully."),
    "Marketplace_product_list_fetched_successfully": _(
        "Marketplace products list fetched successfully."
    ),
    "marketplace_product_created_successfully": _(
        "Product published to marketplace successfully."
    ),
    "jeweler_buyer_dashboard_statistics": _(
        "Dashboard statistics fetched successfully."
    ),
    "sale_list_fetched_successfully": _("Sales list fetched successfully."),
    "sale_details_fetched_successfully": _("Sale details fetched successfully."),
    "sale_updated_successfully": _("Sale updated successfully."),
    "sale_created_successfully": _("Jewelry Sale created successfully."),
    "jewelry_profit_distributions_retrieved": _(
        "Jewelry profit distributions retrieved successfully."
    ),
    "jewelry_profit_distributions_fetched": _(
        "Jewelry profit distributions fetched successfully."
    ),
    "jewelry_profit_distribution_not_found": _(
        "Jewelry profit distribution not found."
    ),
}
