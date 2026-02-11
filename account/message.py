from django.utils.translation import gettext_lazy as _

MESSAGES = {
    # Common messages
    "field_required": _("This field is required."),
    "success": _("Operation completed successfully!"),
    "error": _("Something went wrong. Please try again."),
    "unauthorized": _("Unauthorized access."),
    "password_mismatch": _("Passwords do not match."),
    "password_too_short": _("Your password must be at least 8 characters long."),
    "role_not_found": _("It seems we couldn't find your role in our system."),
    "switch_role_successful": _(f"Switched to role {{role_to_switch}} successfully."),
    "session_success": _("User session details retrieved successfully."),
    "role_mismatch": _("The requested role doesn't match the user's existing role."),
    "already_assigned_role": _(
        f"You are already assigned to the {{role}} role. Please choose a different role to switch."
    ),
    "invalid_fcm_details": _("The FCM details provided are invalid."),
    "user_deleted": _("User deleted successfully."),
    "invalid_phone_number": lambda: _("Please enter a valid phone number."),
    "user_role_fetched": _("User roles fetched successfully."),
    # User registration messages
    "user_created": _("User created successfully!"),
    "user_already_exists": _("User with the email and role already exists."),
    "invalid_role_registration": _(
        "Oops! Registration with team members is not permitted."
    ),
    "role_registration_forbidden": _(
        "You do not have permission to register with this role."
    ),
    "phone_number_exists": _("This phone number already exists."),
    "email_exists": _("This email already exists."),
    "user_updated": _("User updated successfully."),
    "email_registered_but_not_verified": _(
        "This email is already registered. Please log in using this email to complete the registration process."
    ),
    "owner_not_found_in_the_assigne_business": _(
        "Deletion blocked: No owner found for the specified business."
    ),
    # Login messages
    "login_successful": _("Login successful."),
    "invalid_role": _("Please select the proper role of the user."),
    "user_not_found": _(
        "No account found with this email. Please check and try again."
    ),
    "invalid_password": _("Incorrect password. Please try again."),
    "user_suspended": _(
        "Your account has been suspended. Please contact our support team for assistance."
    ),
    # Business-related messages
    "business_created": _("Business created successfully!"),
    "user_business_account_suspended": _(
        "Your business account has been suspended. Please contact our support team for assistance."
    ),
    "business_subscription_suspended": _(
        "Your business subscription has been suspended. Please purchase a paid subscription plan to continue."
    ),
    "business_account_updated": _("Business account updated successfully."),
    "business_account_not_found": _("Business account not found."),
    # Address-related messages
    "address_created": _("Address created successfully!"),
    "address_updated": _("Address updated successfully."),
    "address_deleted": _("Address deleted successfully."),
    "address_retrieved": _("Address retrieved successfully."),
    "address_fetched": _("List of addresses fetched successfully."),
    # Change password messages
    "password_changed_success": _("Password changed successfully!"),
    # Forget password messages
    "otp_verify_success": _("OTP verified successfully."),
    "invalid_otp": _("Invalid OTP."),
    "invalid_token": _("Invalid token."),
    "sent_otp_success": _("OTP has been sent successfully."),
    # Bank related messages
    "bank_account_updated": _("Bank account details updated successfully."),
    # Business details messages
    "business_detail_added": _("Business details added successfully."),
    "business_account_detail_fetched": _(
        "Business account details fetch successfully."
    ),
    "business_document_type_error": _(
        "Invalid business type, please select valid business type"
    ),
    "not_business_owner": _(
        "Only the business owner can update this business details."
    ),
    "required_business_document": _("All required documents must be provided."),
    "invalid_business": _("No business found for the logged-in user."),
    "business_details": _("Business details retrieved successfully."),
    "business_error": _("This business is not for login user."),
    "business_fetched": _("Business fetched successfully."),
    "user_profile_updated": _("User profile updated successfully."),
    "user_profile_not_exists": _("User profile does not exist."),
    "invalid_business_type": _("Invalid type. Only 'WLL' is allowed."),
    "business_account_not_found": _("Business account not found."),
    "business_user_fetched": _("Business users fetched successfully."),
    "business_name_required": _("Business name is required."),
    # Share holder messages
    "share_holder_added": _("Share holder added successfully."),
    "share_holder_not_found": _("Share holder not found."),
    "share_holder_fetched": _("Share holder fetched successfully."),
    "share_holder_deleted": _("Share holder deleted successfully."),
    # Currencies messages
    "currencies_fetched": _("Currencies fetched successfully."),
    "currency_created": _("Organization currency created successfully."),
    "currency_updated": _("Organization currency updated successfully."),
    "currency_already_exists": _(
        "The currency '{currency_code}' already exists for this organization."
    ),
    # Organization error message
    "organization_not_found": _("Organization not found."),
    # Notification message
    "notifications_fetched": _("Notifications fetched successfully."),
    # Business saved cards messages
    "business_saved_cards_fetched": _("Business saved cards fetched successfully."),
    "business_saved_card_added": _("Business card added successfully."),
    "business_default_card_updated": _(
        "Your business card has been set as the default successfully."
    ),
    "business_saved_card_session_created": _(
        "Session created successfully. Proceed with card verification."
    ),
    "business_saved_card_not_found": _("Business saved card not found."),
    "business_saved_card_deleted": _("Business card has been removed successfully."),
    "business_saved_card_cannot_delete_default": _(
        "Cannot delete the default card. Please set another card as default first."
    ),
    # Phone number error message
    "phone_number_exists": _("This phone number already exists."),
    # Sub user message
    "sub_user_created": _("Sub user created successfully."),
    # precious item  error message
    "report_number_required": _("Report number is required."),
    "date_of_issue_required": _("Date of issue is required for GIA certificate type."),
    "precious_item_one_time_error": _("Only one material can be created at a time."),
    "precious_metal_stone_required": _(
        "Either precious_metal or precious_stone is required."
    ),
    "metal_name_weight_exists": _(
        "Precious item with the same metal name and weight already exists."
    ),
    "report_number_exists": _("Report number already exists."),
    "carat_type_required": _("Carat type required."),
    # User preferences message
    "user_preferences_upadated": _("User preferences updated successfully."),
    "user_preferences_fetched": _("User preferences fetched successfully."),
    # Forget password message
    "incorrect_password": _("Incorrect old password. Please try again."),
    # Contact Support message
    "contact_support_request_created": _(
        "Contact support request created successfully."
    ),
    # FCM token message
    "fcm_token_updated": _("FCM token updated successfully."),
    "fcm_token_not_found": _("FCM token not found"),
    "email_not_found": _("No user is associated with this email."),
    # Presigned s3 URL message
    "bucket_name_required": _("Bucket name is required."),
    "file_names_required": _("File names are required."),
    # Notification message
    "notification_not_found": _("Notification not found."),
    "notification_read_unread_status_updated": _(
        "Notification read/unread status updated successfully."
    ),
    "session_expired": _("Your session has expired. Please log in again to proceed."),
    "email_already_verified": _("Email is already verified."),
    "phone_number_already_verified": _("Phone number already verified."),
    "app_version_fetched": _("App version details fetched successfully."),
    # Subscription usage messages
    "subscription_usage_information_retrieved": _(
        "Subscription usage information retrieved successfully."
    ),
}
