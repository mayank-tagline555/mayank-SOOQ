# Subscription Billing System - Developer Guide

## Table of Contents
1. [Overview](#overview)
2. [Recurring Payment Tasks](#recurring-payment-tasks)
3. [Billing Logic Location](#billing-logic-location)
4. [Subscription Status & Verification](#subscription-status--verification)
5. [Plan Transitions](#plan-transitions)
6. [How to Call Billing Functions](#how-to-call-billing-functions)
7. [Testing & Debugging](#testing--debugging)

---

## Overview

The subscription billing system handles three types of recurring payments:
1. **Subscription Fees** (Daily task) - Fixed fees for Sellers, Manufacturers, Jewelers, and non-pro-rata Investors
2. **Pro-Rata Fees** (Yearly on Jan 1) - Investor pro-rata calculations for PREPAID and POSTPAID plans
3. **Commission Fees** (Yearly on Jan 1) - Jeweler commission calculations (placeholder for future)

### Key Concepts

- **Payment Type**: PREPAID (pay upfront) vs POSTPAID (pay after period ends)
- **Payment Interval**: MONTHLY or YEARLY (how often customer pays)
- **Billing Frequency**: MONTHLY or YEARLY (how often invoices are generated)
- **Pending Plans**: Admin can set a new plan that takes effect on the next billing cycle

---

## Recurring Payment Tasks

### Task 1: Subscription Fee Recurring Payment

**Location**: `sooq_althahab/payment_gateway_services/credimax/subscription/tasks.py`

**Function**: `process_subscription_fee_recurring_payment(business_id=None)`

**Schedule**: Daily at 2:00 AM (configured in `settings.py`)

**Handles**:
- Fixed subscription fees for SELLER, MANUFACTURER, JEWELER roles
- Non-pro-rata INVESTOR plans
- PREPAID plans: Charges monthly fee or generates invoice for yearly prepaid
- POSTPAID plans: Charges fee after billing period ends
- Yearly prepaid with monthly billing: Divides yearly fee by 12 for monthly invoices

**Key Logic**:
- Filters subscriptions where `next_billing_date <= today`
- Excludes investors with `pro_rata_rate > 0` (handled by Task 2)
- For yearly prepaid plans: Generates invoice only (no payment)
- For POSTPAID: Only charges if `next_billing_date <= today` (period has ended)

### Task 2: Pro-Rata Recurring Payment

**Location**: `sooq_althahab/payment_gateway_services/credimax/subscription/tasks.py`

**Function**: `process_pro_rata_recurring_payment(business_id=None)`

**Schedule**: Yearly on January 1st at 2:00 AM

**Handles**:
- PREPAID Investors: Recalculates pro-rata for remaining assets
- POSTPAID Investors: Charges accumulated pro-rata from previous year

**Key Logic**:
- Only processes INVESTOR role subscriptions with `pro_rata_rate > 0`
- PREPAID: Recalculates for ALL remaining assets (regardless of purchase date)
- POSTPAID: Charges for previous calendar year, accounting for partial sales

### Task 3: Commission Recurring Payment

**Location**: `sooq_althahab/payment_gateway_services/credimax/subscription/tasks.py`

**Function**: `process_commission_recurring_payment()`

**Status**: Placeholder (not yet implemented - jewelry sales functionality under development)

**Schedule**: Yearly on January 1st at 2:00 AM (currently commented out)

---

## Billing Logic Location

### Core Billing Functions

1. **`calculate_base_amount(subscription, start_date, end_date)`**
   - **Location**: `sooq_althahab/billing/subscription/helpers.py`
   - **Purpose**: Calculates the base billing amount for a subscription
   - **Handles**:
     - POSTPAID → PREPAID transitions (charges both amounts)
     - Yearly/Monthly fee division
     - Pending plan fee calculations
     - Pro-rata calculations

2. **`monthly_subscription_calculation(start_date, end_date, business, business_subscription)`**
   - **Location**: `sooq_althahab/billing/subscription/services.py`
   - **Purpose**: Creates `BillingDetails` record with VAT and tax calculations

3. **`_process_subscription_billing(subscription, client, today)`**
   - **Location**: `sooq_althahab/payment_gateway_services/credimax/subscription/tasks.py`
   - **Purpose**: Main billing processing function (invoice generation, payment, receipts)

### Helper Functions

- **`_generate_invoice_only(subscription, today)`**: Generates invoice without payment (yearly prepaid)
- **`_process_prepaid_pro_rata_recalculation(subscription, client, today)`**: PREPAID pro-rata recalculation
- **`_process_postpaid_pro_rata_charge(subscription, client, today)`**: POSTPAID pro-rata charging
- **`_get_business_display_name(business)`**: Gets business name or owner's fullname

---

## Subscription Status & Verification

### How to Check Subscription Status

```python
from sooq_althahab_admin.models import BusinessSubscriptionPlan
from sooq_althahab.enums.account import SubscriptionStatusChoices

# Get active subscription for a business
subscription = BusinessSubscriptionPlan.objects.filter(
    business=business,
    status=SubscriptionStatusChoices.ACTIVE
).first()

# Check key fields
print(f"Status: {subscription.status}")
print(f"Payment Type: {subscription.payment_type}")
print(f"Next Billing Date: {subscription.next_billing_date}")
print(f"Last Billing Date: {subscription.last_billing_date}")
print(f"Has Pending Plan: {subscription.has_pending_plan_changes()}")
```

### How to Verify Charges

**For POSTPAID Plans**:
- Check if `next_billing_date <= today` (period has ended)
- Check `last_billing_date` to see when last charged
- Review `BillingDetails` records for the billing period

**For PREPAID Plans**:
- Check `next_billing_date` to see when next invoice/payment is due
- For yearly prepaid with monthly billing: Invoice generated monthly, no payment

**For Pending Plan Changes**:
```python
if subscription.pending_subscription_plan:
    print(f"Pending Plan: {subscription.pending_subscription_plan.name}")
    print(f"Effective Date: {subscription.pending_plan_effective_date}")
    print(f"Current Payment Type: {subscription.payment_type}")
    print(f"Pending Payment Type: {subscription.pending_subscription_plan.payment_type}")
```

---

## Plan Transitions

### POSTPAID → PREPAID Transition

**Scenario**: User has POSTPAID subscription, admin sets PREPAID pending plan.

**What Happens on Next Billing Date**:

1. **System Detects Transition**:
   - Current `payment_type == "POSTPAID"`
   - Pending plan `payment_type == "PREPAID"`

2. **Calculates Both Amounts**:
   - **POSTPAID Amount**: Charges for the period that just ended (using current subscription fee)
   - **PREPAID Amount**: Charges for the new plan (using pending subscription fee)
   - Both amounts are combined in a single transaction

3. **Processing**:
   - Single payment transaction for combined amount
   - Single invoice showing both charges
   - After successful payment, pending plan is applied

**Code Location**: `calculate_base_amount()` in `helpers.py` (lines 145-220)

### Other Transitions

- **PREPAID → POSTPAID**: Only charges new POSTPAID amount (old PREPAID already paid)
- **PREPAID → PREPAID**: Only charges new PREPAID amount
- **POSTPAID → POSTPAID**: Only charges new POSTPAID amount

### How Pending Plans Work

1. **Admin Sets Pending Plan**: Updates `pending_subscription_plan` and `pending_plan_effective_date`
2. **Next Billing Cycle**:
   - Billing uses pending plan fee (if effective date reached)
   - After successful payment, `apply_pending_plan_changes()` is called
   - Pending plan becomes active, pending fields cleared

**Key Method**: `apply_pending_plan_changes()` in `BusinessSubscriptionPlan` model

---

## How to Call Billing Functions

### Manual Testing for Specific Business

```python
from sooq_althahab.payment_gateway_services.credimax.subscription.tasks import (
    process_subscription_fee_recurring_payment,
    process_pro_rata_recurring_payment,
)

# Test subscription fee billing for specific business
business_id = "bus_311225d1294a"
process_subscription_fee_recurring_payment(business_id=business_id)

# Test pro-rata billing for specific business
process_pro_rata_recurring_payment(business_id=business_id)
```

### Check Billing Details

```python
from sooq_althahab_admin.models import BillingDetails
from sooq_althahab.enums.sooq_althahab_admin import PaymentStatus

# Get billing details for a business
billing_details = BillingDetails.objects.filter(
    business=business,
    payment_status=PaymentStatus.COMPLETED
).order_by('-created_at')

for billing in billing_details:
    print(f"Period: {billing.period_start_date} to {billing.period_end_date}")
    print(f"Amount: {billing.total_amount}")
    print(f"Status: {billing.payment_status}")
```

### Verify Transactions

```python
from account.models import Transaction
from sooq_althahab.enums.account import TransactionStatus

# Get successful subscription transactions
transactions = Transaction.objects.filter(
    from_business=business,
    transaction_type="PAYMENT",
    status=TransactionStatus.SUCCESS,
    business_subscription__isnull=False
).order_by('-created_at')
```

---

## Testing & Debugging

### Common Scenarios to Test

1. **Yearly Prepaid with Monthly Billing**:
   - Verify invoice shows yearly_fee / 12
   - Verify no payment is processed
   - Verify `next_billing_date` updates correctly

2. **POSTPAID → PREPAID Transition**:
   - Set pending PREPAID plan on POSTPAID subscription
   - Wait for `next_billing_date`
   - Verify both amounts are charged in single transaction
   - Verify pending plan is applied after payment

3. **POSTPAID Pro-Rata**:
   - Create POSTPAID investor with purchases
   - Run pro-rata task on Jan 1
   - Verify charges for previous year
   - Verify partial sales are accounted for

### Debug Logging

All billing tasks use structured logging with prefixes:
- `[SUBSCRIPTION-FEE-TASK]` - Subscription fee billing
- `[PRO-RATA-TASK]` - Pro-rata billing
- `[BILLING]` - Billing calculations

### Key Database Fields to Monitor

- `BusinessSubscriptionPlan.next_billing_date` - When next billing occurs
- `BusinessSubscriptionPlan.last_billing_date` - Last successful billing
- `BusinessSubscriptionPlan.billing_cycle_count` - Number of cycles completed
- `BusinessSubscriptionPlan.pending_subscription_plan` - Pending plan changes
- `BillingDetails.payment_status` - Payment status (PENDING, COMPLETED, FAILED)
- `Transaction.status` - Transaction status (SUCCESS, FAILED, PENDING)

---

## Important Notes

1. **Yearly Prepaid Plans**:
   - Payment made upfront
   - Monthly invoices generated for documentation only
   - No payment processed on monthly billing dates

2. **POSTPAID Plans**:
   - Only charged AFTER billing period ends (`next_billing_date <= today`)
   - Charges accumulated fees from the period

3. **Pending Plans**:
   - Take effect on next billing cycle
   - Billing uses pending plan fee if effective date reached
   - Applied after successful payment

4. **Pro-Rata Calculations**:
   - PREPAID: Recalculated yearly for remaining assets
   - POSTPAID: Charged yearly for previous year's accumulated fees

---

## File Structure

```
sooq_althahab/
├── billing/
│   └── subscription/
│       ├── helpers.py          # calculate_base_amount, utility functions
│       └── services.py          # monthly_subscription_calculation, email functions
├── payment_gateway_services/
│   └── credimax/
│       └── subscription/
│           ├── tasks.py        # All recurring payment tasks
│           └── SUBSCRIPTION_BILLING_GUIDE.md  # This file
└── sooq_althahab_admin/
    └── models.py                # BusinessSubscriptionPlan model
```

---

## Support

For questions or issues:
1. Check logs for `[SUBSCRIPTION-FEE-TASK]` or `[PRO-RATA-TASK]` prefixes
2. Review `BillingDetails` and `Transaction` records
3. Verify `next_billing_date` and `last_billing_date` fields
4. Check for pending plan changes
