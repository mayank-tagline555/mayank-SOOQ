# Update Business Subscription Plan API

## Overview

This API allows administrators to update the subscription plan for a given business. The API handles all necessary changes to ensure the business subscription plan is properly updated, including billing cycle adjustments, musharakah limitations, jewelry design limitations, and other subscription-related configurations.

## Endpoint

```
PATCH /api/v1/subscription/update-business-plan/
```

## Authentication

- **Required**: Yes
- **Type**: Bearer Token (IsAuthenticated permission)

## Request Payload

```json
{
  "business_id": "bus_123456789",
  "subscription_plan_id": "sp_987654321"
}
```

### Parameters

| Parameter              | Type   | Required | Description                                       |
| ---------------------- | ------ | -------- | ------------------------------------------------- |
| `business_id`          | string | Yes      | The ID of the business to update subscription for |
| `subscription_plan_id` | string | Yes      | The ID of the new subscription plan to assign     |

## Response

### Success Response (200 OK)

```json
{
  "success": true,
  "message": "Business subscription plan update scheduled for next billing cycle",
  "data": {
    "subscription_id": "bsp_123456789",
    "business_name": "Gold Jewelry LLC",
    "current_plan_name": "Basic Plan",
    "pending_plan_name": "Premium Plan",
    "current_billing_cycle": {
      "uses_plan": "Basic Plan",
      "subscription_fee": "100.00",
      "commission_rate": "0.0500",
      "billing_period": "2025-10-13 to 2025-11-13"
    },
    "pending_changes": {
      "effective_date": "2025-11-13",
      "new_plan_name": "Premium Plan",
      "new_subscription_fee": "150.00",
      "new_commission_rate": "0.0700",
      "will_apply_on_next_billing": true
    },
    "subscription_dates": {
      "start_date": "2025-10-13",
      "expiry_date": "2026-10-13",
      "next_billing_date": "2025-11-13",
      "duration_months": 12
    },
    "billing_details_impact": {
      "next_billing_info": {
        "next_billing_date": "2025-11-13",
        "will_use_new_rates": true,
        "billing_cycle_preserved": true,
        "last_billing_date": "2025-10-13"
      },
      "plan_change_effective_date": "2025-11-13"
    },
    "limitations_impact": {
      "musharakah": {
        "musharakah_request_max_weight": {
          "old_limit": "100.00",
          "new_limit": "500.00"
        },
        "metal_purchase_max_weight": {
          "old_limit": "50.00",
          "new_limit": "200.00"
        }
      },
      "design": {
        "max_design_count": {
          "old_limit": 5,
          "new_limit": 20
        }
      }
    }
  }
}
```

**Note**: The response clearly indicates that:
- Current billing cycle (Oct 13 - Nov 13) will use the "Basic Plan" with original rates
- Changes are stored as pending (only plan reference + effective date)
- Changes will automatically apply on Nov 13 by reading all values from the new plan
- Next billing cycle (Nov 13 - Dec 13) will use the "Premium Plan" with new rates

### Error Responses

#### 400 Bad Request - Validation Error

```json
{
  "success": false,
  "error": "Business not found."
}
```

#### 404 Not Found - Subscription Plan Not Found

```json
{
  "success": false,
  "error": "Subscription plan not found or inactive."
}
```

#### 400 Bad Request - No Active Subscription

```json
{
  "success": false,
  "error": "Business does not have an active subscription to update."
}
```

#### 400 Bad Request - Role Mismatch

```json
{
  "success": false,
  "error": "Subscription plan role 'JEWELER' does not match business role 'SELLER'."
}
```

#### 500 Internal Server Error

```json
{
  "success": false,
  "error": "Failed to update business subscription plan: [error details]"
}
```

## Business Logic

### 1. Validation

- **Business Existence**: Verifies the business exists and is accessible
- **Subscription Plan**: Ensures the new subscription plan exists and is active
- **Active Subscription**: Confirms the business has an active subscription to update
- **Role Compatibility**: Validates that the subscription plan role matches the business role

### 2. Subscription Plan Updates - Pending Plan Mechanism

**CRITICAL: The API uses a simple PENDING PLAN mechanism to ensure current billing cycle integrity.**

Instead of immediately updating the active subscription fields, the API stores a reference to the new plan that will be automatically applied at the start of the next billing cycle.

#### Simple Pending Fields (Only 2 fields):

- `pending_subscription_plan` - ForeignKey reference to the new subscription plan
- `pending_plan_effective_date` - Date when the new plan takes effect (next_billing_date)

#### How It Works:

1. **Admin updates plan**: We store only the plan ID and effective date
2. **Current cycle continues**: All active fields remain unchanged
3. **Next billing date arrives**: System reads all values from the pending plan and updates active fields
4. **New cycle starts**: Uses the new plan rates

#### Active Fields (Remain Unchanged until effective date):

- `subscription_plan` - Current active subscription plan
- `subscription_name` - Current plan name
- `subscription_fee` - Current subscription fee
- `commission_rate` - Current commission rate
- `billing_frequency` - Current billing frequency
- All other billing configuration fields

### 3. Billing Cycle Management

**How Pending Changes Are Applied:**

1. **Admin Updates Plan (e.g., Oct 20)**: Changes are stored in pending fields
2. **Current Billing Cycle Continues**: Uses original plan rates until next billing date
3. **Next Billing Date Arrives (e.g., Nov 13)**: System automatically applies pending changes
4. **New Billing Cycle Starts**: Uses the updated plan rates

**Automatic Application Logic:**

- Before creating billing details, the system checks `should_apply_pending_changes()`
- If `pending_plan_effective_date <= current_date`, calls `apply_pending_plan_changes()`
- Pending fields are moved to active fields and pending fields are cleared
- Billing then proceeds with the updated active plan

### 4. Billing Details Management

The API follows **fintech industry standards** for billing cycle management:

#### Financial Integrity Principles:

- **NO Updates to Existing Bills**: Existing billing details are never modified
- **NO Immediate Plan Changes**: Changes stored as pending, not applied immediately
- **Current Cycle Protection**: Current billing cycle always uses the original plan rates
- **Future Bills Only**: New subscription plan rates only apply to future billing cycles
- **Automatic Transition**: Pending changes applied automatically at next billing cycle

#### Billing Cycle Logic Example:

```
Scenario: Subscription activated Oct 13, plan updated Oct 20

Timeline:
- Oct 13: Subscription activated with Plan A (Fee: $100, Commission: 5%)
- Oct 20: Admin updates to Plan B (Fee: $150, Commission: 7%)
  → Changes stored in pending fields
  → pending_plan_effective_date set to Nov 13 (next_billing_date)
  → Current plan remains Plan A

- Oct 13 - Nov 13 (Current Billing Cycle):
  → Uses Plan A rates (Fee: $100, Commission: 5%)
  → Active subscription_fee = $100
  → Active commission_rate = 5%

- Nov 13 (Next Billing Date):
  → System checks: should_apply_pending_changes(Nov 13) → TRUE
  → Calls apply_pending_plan_changes()
  → Moves pending fields to active fields
  → Active subscription_fee = $150
  → Active commission_rate = 7%
  → Clears all pending fields

- Nov 13 - Dec 13 (Next Billing Cycle):
  → Uses Plan B rates (Fee: $150, Commission: 7%)
```

#### Billing Details Impact Tracking:

The API response includes detailed information about pending changes:

- **current_billing_cycle**: Shows which plan and rates the current cycle uses
- **pending_changes**: Shows what will change and when
- **effective_date**: When the new plan takes effect (next_billing_date)
- **current_plan_name**: The plan currently in effect
- **pending_plan_name**: The plan that will take effect
- **will_apply_on_next_billing**: Confirmation that changes are deferred

### 5. Business Limitations (JEWELER Role Only)

#### Musharakah Limitations

- **Musharakah Request Max Weight**: Maximum metal weight for musharakah requests
- **Metal Purchase Max Weight**: Maximum metal weight for direct purchases
- **Usage Validation**: Checks if current usage exceeds new limits and provides warnings

#### Jewelry Design Limitations

- **Max Design Count**: Maximum number of designs the jeweler can upload
- **Usage Validation**: Checks if current design count exceeds new limits and provides warnings

### 6. Impact Analysis

The API provides detailed impact analysis including:

- **Updated Fields**: List of all fields that were changed
- **Billing Impact**: Changes to billing configuration and fees
- **Limitations Impact**: Changes to business limitations with warnings for potential issues

## Usage Examples

### Example 1: Upgrading from Monthly to Yearly Plan

**Request:**

```json
{
  "business_id": "bus_abc123",
  "subscription_plan_id": "sp_yearly_premium"
}
```

**Response:**

```json
{
  "success": true,
  "message": "Business subscription plan updated successfully",
  "data": {
    "subscription_id": "bsp_def456",
    "business_name": "Gold Jewelers Inc",
    "old_plan_name": "Monthly Basic Plan",
    "new_plan_name": "Yearly Premium Plan",
    "updated_fields": [
      "subscription_plan",
      "subscription_name",
      "billing_frequency",
      "subscription_fee",
      "next_billing_date"
    ],
    "billing_impact": {
      "old_billing_frequency": "MONTHLY",
      "new_billing_frequency": "YEARLY",
      "old_subscription_fee": "100.00",
      "new_subscription_fee": "1200.00"
    }
  }
}
```

### Example 2: Updating JEWELER Limitations

**Request:**

```json
{
  "business_id": "bus_jeweler123",
  "subscription_plan_id": "sp_jeweler_premium"
}
```

**Response:**

```json
{
  "success": true,
  "message": "Business subscription plan updated successfully",
  "data": {
    "subscription_id": "bsp_jeweler456",
    "business_name": "Diamond Crafters",
    "old_plan_name": "Jeweler Basic",
    "new_plan_name": "Jeweler Premium",
    "updated_fields": [
      "subscription_plan",
      "subscription_name",
      "subscription_fee"
    ],
    "limitations_impact": {
      "musharakah": {
        "musharakah_request_max_weight": {
          "old_limit": "100.00",
          "new_limit": "500.00"
        }
      },
      "design": {
        "max_design_count": {
          "old_limit": 5,
          "new_limit": 20
        }
      }
    }
  }
}
```

## Security Considerations

1. **Authentication Required**: Only authenticated users can access this endpoint
2. **Admin Access**: Should be restricted to admin users only (consider adding admin permission check)
3. **Business Validation**: Ensures the business exists and is accessible
4. **Role Validation**: Prevents assigning incompatible subscription plans

## Error Handling

- **Database Transactions**: All updates are wrapped in database transactions for consistency
- **Validation Errors**: Comprehensive validation with clear error messages
- **Logging**: All updates are logged for audit purposes
- **Rollback**: Failed updates are automatically rolled back

## Integration Points

This API integrates with:

- **Billing System**: Updates billing cycles and fee calculations
- **Musharakah System**: Handles weight limitations for jeweler businesses
- **Jewelry Design System**: Manages design count limitations
- **Subscription Management**: Updates subscription plan references and configurations

## Notes

- The API preserves the existing subscription history and billing cycle count
- Only ACTIVE and TRIALING subscriptions can be updated
- The system maintains backward compatibility with existing subscriptions
- All changes are logged for audit and debugging purposes
