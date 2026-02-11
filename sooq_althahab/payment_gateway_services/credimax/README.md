# Credimax Transaction Status Checker

This module provides functionality to check the status of pending Credimax transactions by calling the Credimax API. This serves as a fallback mechanism in case webhooks are missed or fail to process.

## Features

- **Automated Task**: Runs every 5 minutes to check all pending Credimax transactions
- **Individual Transaction Checking**: Can check the status of a single transaction
- **Wallet Balance Updates**: Automatically updates wallet balances for successful deposits
- **Webhook Call Logging**: Logs all status checks for audit purposes
- **Retry Mechanism**: Implements exponential backoff for failed API calls
- **Management Command**: Manual execution for testing and debugging

## How It Works

1. **Scheduled Task**: The `check_pending_credimax_transactions` task runs every 5 minutes
2. **Transaction Query**: Finds all transactions with `status=PENDING` and `transfer_via=CREDIMAX`
3. **API Call**: For each transaction, calls the Credimax API endpoint: `GET /api/rest/version/100/merchant/{merchantId}/order/{orderId}`
4. **Status Update**: Updates transaction status based on Credimax response:
   - `SUCCESS` + `CAPTURED` → `SUCCESS`
   - `FAILURE` or `DECLINED`/`CANCELLED`/`EXPIRED` → `FAILED`
   - `AUTHORIZED`/`PENDING` → `PENDING` (no change)
5. **Wallet Update**: For successful deposits, updates the business wallet balance
6. **Audit Logging**: Creates WebhookCall records for all status checks

## API Endpoint

The task calls the Credimax order status endpoint:
```
GET https://credimax.gateway.mastercard.com/api/rest/version/100/merchant/{merchantId}/order/{orderId}
```

Where:
- `{merchantId}` is the Credimax merchant ID from settings
- `{orderId}` is the transaction ID (as used in the checkout process)

## Configuration

The task is configured in `sooq_althahab/settings.py`:

```python
CELERY_BEAT_SCHEDULE = {
    "check_pending_credimax_transactions": {
        "task": "sooq_althahab.payment_gateway_services.credimax.tasks.check_pending_credimax_transactions",
        "schedule": crontab(minute="*/5"),  # Every 5 minutes
        "options": {"queue": "default"},
    },
}
```

## Usage

### Automated Execution

The task runs automatically every 5 minute via Celery Beat. No manual intervention required.

### Manual Execution

You can manually run the task using the Django management command:

```bash
# Run the task
python manage.py check_credimax_transactions

# Run in dry-run mode (shows what would be processed)
python manage.py check_credimax_transactions --dry-run
```

### Programmatic Execution

You can also run the task programmatically:

```python
from sooq_althahab.payment_gateway_services.credimax.tasks import check_pending_credimax_transactions

# Run asynchronously
result = check_pending_credimax_transactions.delay()

# Run synchronously
result = check_pending_credimax_transactions.apply()
```

## Error Handling

- **API Errors**: Retries up to 3 times with exponential backoff (5 minutes, 10 minutes, 20 minutes)
- **Transaction Not Found**: Logs error and continues with next transaction
- **Wallet Not Found**: Logs error and raises exception
- **Unknown Status**: Logs warning and keeps transaction as pending

## Logging

All operations are logged with the prefix `[Credimax-Task]` for easy filtering:

```python
logger.info("[Credimax-Task] Starting to check pending Credimax transactions")
logger.info("[Credimax-Task] Found 5 pending Credimax transactions")
logger.info("[Credimax-Task] Updated transaction ABC123 status from PENDING to SUCCESS")
```

## Monitoring

Monitor the task execution through:

1. **Celery Logs**: Check Celery worker logs for task execution
2. **Django Logs**: Look for `[Credimax-Task]` prefixed messages
3. **Database**: Check WebhookCall records for audit trail
4. **Transaction Status**: Monitor transaction status changes in the database

## Security Considerations

- Uses the same authentication credentials as the main Credimax integration
- API calls are made with proper timeout (30 seconds)
- All sensitive data is logged at DEBUG level only
- Webhook call records provide audit trail for all status checks

## Troubleshooting

### Task Not Running
- Check if Celery Beat is running: `celery -A sooq_althahab beat --loglevel=info`
- Verify task is in CELERY_BEAT_SCHEDULE
- Check Celery worker logs for errors

### API Errors
- Verify Credimax credentials in settings
- Check network connectivity to Credimax API
- Review API response logs for specific error messages

### Transaction Status Not Updating
- Check if transaction exists in database
- Verify transaction has correct `transfer_via=CREDIMAX`
- Review Credimax API response for unexpected status values
