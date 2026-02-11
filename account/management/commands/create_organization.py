from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from account.models import Organization
from account.models import OrganizationCurrency


class Command(BaseCommand):
    help = "Create an organization with specified details."

    def add_arguments(self, parser):
        parser.add_argument("--name", type=str, help="Name of the organization")
        parser.add_argument(
            "--arabic_name", type=str, help="Arabic name of the organization"
        )
        parser.add_argument(
            "--description", type=str, help="Description of the organization"
        )
        parser.add_argument("--country", type=str, help="Country of the organization")
        parser.add_argument("--address", type=str, help="Address of the organization")
        parser.add_argument(
            "--commercial_registration_number",
            type=str,
            help="Commercial registration number",
        )
        parser.add_argument(
            "--vat_account_number",
            type=str,
            help="Vat account number",
        )
        parser.add_argument("--timezone", type=str, help="Timezone of the organization")
        parser.add_argument(
            "--currency_code",
            type=str,
            help="Currency code for country of the organization",
        )
        parser.add_argument(
            "--rate", type=str, help="Exchange rate for country of the organization"
        )

    def get_input(self, field_name, value=None):
        """Prompt user for input if the value is None, otherwise return the provided value."""
        return value or input(f"{field_name}: ")

    def handle(self, *args, **options):
        # Prepare the fields and get input where necessary
        organization_data = {
            "name": options["name"],
            "arabic_name": options.get("arabic_name"),
            "description": options.get("description"),
            "country": options.get("country"),
            "address": options.get("address"),
            "commercial_registration_number": options.get(
                "commercial_registration_number"
            ),
            "vat_account_number": options.get("vat_account_number"),
            "timezone": options.get("timezone"),
            "currency_code": options.get("currency_code"),
            "exchange_rate": options.get("exchange_rate"),
        }

        # Prompt for input for any missing fields
        for field, value in organization_data.items():
            organization_data[field] = self.get_input(field, value)

        # Extract default currency data for the organization.
        organization_currency_data = {
            "currency_code": organization_data.pop("currency_code"),
            "rate": organization_data.pop("exchange_rate"),
            "is_default": True,
        }

        # Check if the organization already exists
        if Organization.objects.filter(name=organization_data["name"]).exists():
            raise CommandError(
                f"An organization with the name '{organization_data['name']}' already exists."
            )

        # Create the organization
        organization = Organization(**organization_data)
        organization.save()

        # Create the Organization currency
        organization_currency_data["organization"] = organization
        organization_currency = OrganizationCurrency(**organization_currency_data)
        organization_currency.save()

        # Output success message
        self.stdout.write(
            self.style.SUCCESS(
                f"Organization with id '{organization.id}' created successfully!"
            )
        )
