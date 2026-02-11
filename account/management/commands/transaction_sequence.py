from django.core.management.base import BaseCommand

from account.models import ReceiptSequence
from account.models import Transaction
from investor.models import PurchaseRequest


class Command(BaseCommand):
    help = "Backfill ReceiptSequence using Transaction and PurchaseRequest numbers."

    def handle(self, *args, **kwargs):
        # Handle Transactions
        for tx in Transaction.objects.exclude(receipt_number__isnull=True):
            receipt = tx.receipt_number.strip()

            if len(receipt) < 13:
                continue

            mm_yy = receipt[3:7]
            transaction_code = receipt[7:10]

            try:
                sequence_number = int(receipt[10:])
            except ValueError:
                continue

            obj, _ = ReceiptSequence.objects.get_or_create(
                mm_yy=mm_yy,
                transaction_code=transaction_code,
                defaults={"last_sequence": sequence_number},
            )
            if sequence_number > obj.last_sequence:
                obj.last_sequence = sequence_number
                obj.save()

        # Handle Purchase Requests
        for pr in PurchaseRequest.objects.exclude(invoice_number__isnull=True):
            receipt = pr.invoice_number.strip()

            if len(receipt) < 13:
                continue

            transaction_code = receipt[:3]  # INV
            mm_yy = receipt[6:10]  # 0725

            try:
                sequence_number = int(receipt[10:])
            except ValueError:
                continue

            obj, _ = ReceiptSequence.objects.get_or_create(
                mm_yy=mm_yy,
                transaction_code=transaction_code,
                defaults={"last_sequence": sequence_number},
            )
            if sequence_number > obj.last_sequence:
                obj.last_sequence = sequence_number
                obj.save()

        self.stdout.write(
            self.style.SUCCESS("Receipt sequence data synced successfully.")
        )
