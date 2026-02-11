# Subscription System Documentation

## Overview

This document provides a comprehensive understanding of the subscription system in the Sooq Al Thahab platform, covering subscription creation, system operation, and the impact of plan updates on existing users.

## 1. How is a Subscription Created?

### 1.1 Subscription Plan Creation (Admin Level)

Subscription plans are created by adminis through the Django admin interface or API endpoints. The process involves:

**Admin Interface (`SubscriptionPlanAdmin`):**

- **Basic Information**: Name, role (SELLER, JEWELER, INVESTOR, MANUFACTURER), business type, subscription code, description, and active status
- **Billing Configuration**: Duration (in months), billing frequency, payment interval, payment amount variability, and payment type (PREPAID/POSTPAID)
- **Pricing**: Subscription fee, discounted fee, commission rate, and pro-rata rate
- **Free Trial Limitations**: For JEWELER role only - maximum metal weight, design count, and other usage limits

**API Endpoints:**

- `POST /subscription-plans/` - Creates new subscription plans
- `PATCH /subscription-plans/{id}/` - Updates existing plans
- `DELETE /subscription-plans/{id}/` - Deletes plans

**Key Fields in SubscriptionPlan Model:**

```python
class SubscriptionPlan:
    name = models.CharField(max_length=100)
    role = models.CharField(max_length=30, choices=UserRoleBusinessChoices)
    subscription_code = models.CharField(max_length=12, unique=True)
    duration = models.PositiveIntegerField(default=12)  # months
    billing_frequency = models.CharField(choices=SubscriptionBillingFrequencyChoices)
    payment_interval = models.CharField(choices=SubscriptionPaymentIntervalChoices)
    subscription_fee = models.DecimalField(max_digits=10, decimal_places=2)
    payment_type = models.CharField(choices=SubscriptionPaymentTypeChoices)
    is_active = models.BooleanField(default=True)
```

### 1.2 User Subscription Creation

When users subscribe to a plan, the system creates a `BusinessSubscriptionPlan` instance:

**Subscription Process:**

1. **Plan Selection**: User selects an active subscription plan
2. **Payment Processing**: Integration with Credimax payment gateway for 3DS authentication
3. **Subscription Creation**: System creates `BusinessSubscriptionPlan` with:
   - Business/User account reference
   - Subscription plan reference
   - Start date and calculated expiry date
   - Billing configuration (billing day, frequency, auto-renew settings)
   - Payment method token storage

**Key Fields in BusinessSubscriptionPlan Model:**

```python
class BusinessSubscriptionPlan:
    business = models.ForeignKey(BusinessAccount, on_delete=models.CASCADE)
    subscription_plan = models.ForeignKey(SubscriptionPlan, on_delete=models.SET_NULL)
    start_date = models.DateField()
    expiry_date = models.DateField()
    billing_day = models.PositiveIntegerField(default=1)
    next_billing_date = models.DateField()
    billing_frequency = models.CharField()
    payment_interval = models.CharField()
    subscription_fee = models.DecimalField()
    status = models.CharField(choices=SubscriptionStatusChoices)
    is_auto_renew = models.BooleanField(default=True)
```

## 2. How Does the Subscription System Work After Creation?

### 2.1 Subscription Lifecycle Management

The subscription system operates through several automated processes:

**Status Management:**

- **PENDING**: Initial state during payment processing
- **ACTIVE**: Active subscription with full access
- **TRIALING**: Free trial period (for applicable plans)
- **SUSPENDED**: Temporarily suspended due to payment issues
- **CANCELLED**: User-cancelled subscription
- **EXPIRED**: Subscription has reached its end date
- **TERMINATED**: Admin-terminated subscription

**Billing Cycle Management:**

- **Billing Day**: Configurable day of month for billing (1-31)
- **Next Billing Date**: Automatically calculated based on billing frequency
- **Billing Cycle Count**: Tracks completed billing cycles
- **Grace Period**: Configurable retry attempts for failed payments

### 2.2 Automated Billing and Renewal

The system uses Celery tasks for automated subscription management:

**Recurring Payment Tasks:**

The system uses three separate Celery tasks for automated subscription management:

- **Subscription Fee Recurring Task** (`process_subscription_fee_recurring_payment`):
  - Runs daily at 2:00 AM
  - Handles fixed subscription fees for Sellers, Manufacturers, Jewelers, and non-pro-rata Investors
  - Processes PREPAID and POSTPAID plans based on billing cycles

- **Pro-Rata Recurring Task** (`process_pro_rata_recurring_payment`):
  - Runs yearly on January 1st at 2:00 AM
  - Handles investor pro-rata calculations for PREPAID and POSTPAID plans

- **Commission Recurring Task** (`process_commission_recurring_payment`):
  - Runs yearly on January 1st at 2:00 AM
  - Placeholder for future jeweler commission calculations (jewelry sales functionality under development)

**Note**: The old `process_recurring_subscription_payments()` and `generate_monthly_billing_for_all_businesses()` tasks have been deprecated and removed.

**Payment Processing:**

- **Token Storage**: Secure storage of payment method tokens
- **Recurring Charges**: Automatic charging using stored tokens
- **VAT Calculation**: Automatic VAT calculation based on organization vat rates
- **Transaction Recording**: Complete audit trail of all payments

### 2.3 Free Trial Management

Special handling for free trial subscriptions:

**Free Trial Features:**

- **No Payment Required**: Immediate activation without payment processing
- **Usage Limitations**: Configurable limits for metal weight, design count, etc.
- **Automatic Expiry**: Trial period based on plan duration
- **Upgrade Path**: Seamless transition to paid plans

## 3. Impact of Subscription Plan Updates on Existing Users

### 3.1 **No Impact on Existing Users**

**Critical Design Decision:**
The system is designed so that **admin updates to existing subscription plans do NOT affect users who are already subscribed**. This is achieved through a specific database relationship design:

**Database Relationship:**

```python
class BusinessSubscriptionPlan:
    subscription_plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.SET_NULL,  # Key design decision
        null=True,
        blank=True,
        related_name="business_subscription_plan",
    )
```

### 3.2 Why Existing Users Are Protected

**1. SET_NULL on Delete:**

- If a subscription plan is deleted, existing user subscriptions remain intact
- The `subscription_plan` field becomes `NULL` but the subscription continues
- Users maintain their current subscription terms and billing

**2. Snapshot of Plan Details:**

- When a user subscribes, the system creates a snapshot of the plan details
- Key information is copied to the `BusinessSubscriptionPlan` instance:
  - `subscription_fee` (copied from plan)
  - `billing_frequency` (copied from plan)
  - `payment_interval` (copied from plan)
  - `payment_amount_variability` (copied from plan)
  - `payment_type` (copied from plan)

**3. Independent Billing Cycles:**

- Each user subscription maintains its own billing cycle
- Billing dates are calculated independently for each subscription
- Changes to the original plan template don't affect ongoing billing

### 3.3 What This Means in Practice

**For Admins:**

- Can modify subscription plans for new users without affecting existing subscribers
- Can update pricing, features, and terms for future subscribers
- Can deactivate or modify plans without disrupting current users

**For Existing Users:**

- Continue paying the same fee they originally agreed to
- Maintain the same billing cycle and terms
- Are not affected by plan changes, price increases, or feature modifications
- Can continue using the service under their original agreement terms

**For New Users:**

- Will see and subscribe to the updated plan terms
- Will pay the new pricing and have access to new features
- Will be subject to any new limitations or requirements

### 3.4 Business Benefits of This Design

**1. Customer Protection:**

- Prevents unexpected price increases for existing customers
- Maintains trust and customer satisfaction
- Reduces customer service issues related to plan changes

**2. Business Flexibility:**

- Allows for competitive pricing adjustments
- Enables feature additions and improvements
- Supports market-driven plan evolution

**3. Compliance and Legal:**

- Maintains the integrity of existing contracts
- Prevents retroactive changes to agreed terms
- Supports regulatory compliance requirements

## Summary

The subscription system in Sooq Al Thahab is designed with a clear separation between plan templates and user subscriptions. This architecture ensures that:

1. **Admins can create and manage subscription plans** through a comprehensive admin interface
2. **Users subscribe to plans** through a secure payment process that creates independent subscription instances
3. **The system operates automatically** with daily billing cycles and monthly invoice generation
4. **Existing users are protected** from plan changes through a snapshot-based design that maintains their original terms

This design provides both business flexibility and customer protection, allowing the platform to evolve its offerings while maintaining the trust and satisfaction of existing subscribers.
