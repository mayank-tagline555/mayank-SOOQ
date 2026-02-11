class BusinessDetailsMixin:
    """
    Mixin to dynamically serialize a related business-like field on any object.
    """

    def serialize_business(self, obj, attr_name: str):
        """
        Dynamically fetches and serializes the business-related field.

        Args:
            obj: The model instance.
            attr_name (str): The attribute name to fetch from obj (e.g., "business", "jeweler").
        """
        from .serializers import BusinessAccountDetailsSerializer

        related_obj = getattr(obj, attr_name, None)
        if related_obj:
            return BusinessAccountDetailsSerializer(related_obj).data
        return None


class ReceiptNumberMixin:
    def generate_receipt_number(
        self,
        users_business,
        transaction_type=None,
        model_cls=None,
        subscription_code=None,
    ):
        """Generate a unique receipt number for a given model type."""
        from django.db import transaction
        from django.utils.timezone import now

        from account.models import ReceiptSequence
        from account.models import Transaction
        from account.models import UserAssignedBusiness
        from investor.models import PurchaseRequest
        from sooq_althahab_admin.models import BillingDetails

        current_time = now()
        mm_yy = current_time.strftime("%m%y")

        if users_business and users_business.name:
            business_initials = users_business.name[:3].upper()
        else:
            user_assigned_business = UserAssignedBusiness.objects.filter(
                business=users_business, is_owner=True
            ).first()

            if user_assigned_business and user_assigned_business.user:
                user = user_assigned_business.user
                fullname = user.fullname.strip()
                if fullname:
                    business_initials = "".join(
                        [part[0].upper() for part in fullname.split() if part]
                    )[:3]
                else:
                    business_initials = "USR"
            else:
                business_initials = "USR"

        if model_cls == Transaction:
            # Format: <BUSINESS_INITIALS><MMYY><TRANSACTION_CODE><SEQUENCE>
            # Example: TAG0625TUP001
            # Prefix mapping: TUP = Top-up/Deposit, WDR = Withdrawal, TRF = Transfer
            TRANSACTION_PREFIXES = {
                "WITHDRAWAL": "WDR",
                "DEPOSIT": "TUP",
                "PAYMENT": "TRF",
            }
            transaction_code = TRANSACTION_PREFIXES.get(transaction_type.upper(), "TRX")

        elif model_cls == BillingDetails:
            # Billing receipt format: <BUSINESS_INITIALS>SCP<SUBSCRIPTION_CODE><MMYY><SEQUENCE>
            # Example: TAGSCPS0625001
            # SCP = Subscription Code Prefix
            # SUB = Default subscription code if not provided
            if not subscription_code:
                subscription_code = "SUB"

            # Use daily count per month as a simple sequence (you can also migrate this to ReceiptSequence if needed)
            monthly_count = (
                BillingDetails.objects.filter(
                    created_at__year=current_time.year,
                    created_at__month=current_time.month,
                ).count()
                + 1
            )
            return f"{business_initials}SCP{subscription_code.upper()}{mm_yy}{monthly_count:03d}"

        elif model_cls == PurchaseRequest:
            transaction_code = "INV"
        else:
            raise ValueError("Unsupported model type for receipt number generation.")

        # Shared atomic logic for sequence tracking
        with transaction.atomic():
            sequence_obj, _ = ReceiptSequence.objects.select_for_update().get_or_create(
                mm_yy=mm_yy,
                transaction_code=transaction_code,
                defaults={"last_sequence": 0},
            )
            sequence_obj.last_sequence += 1
            sequence_obj.save()

        return (
            f"{transaction_code}{business_initials}{mm_yy}{sequence_obj.last_sequence:03d}"
            if model_cls == PurchaseRequest
            else f"{business_initials}{mm_yy}{transaction_code}{sequence_obj.last_sequence:03d}"
        )
