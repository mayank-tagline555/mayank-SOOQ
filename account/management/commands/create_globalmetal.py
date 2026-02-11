from django.core.management.base import BaseCommand

from account.models import AdminUserRole
from sooq_althahab.enums.account import UserRoleChoices
from sooq_althahab.enums.sooq_althahab_admin import MaterialType
from sooq_althahab_admin.models import GlobalMetal
from sooq_althahab_admin.models import MaterialItem


class Command(BaseCommand):
    help = "Create predefined global metals"

    METALS = [
        {"name": "Gold", "symbol": "XAU"},
        {"name": "Silver", "symbol": "XAG"},
        {"name": "Platinum", "symbol": "XPT"},
        {"name": "Palladium", "symbol": "XPD"},
    ]

    def handle(self, *args, **kwargs):
        admin_user = AdminUserRole.objects.filter(role=UserRoleChoices.ADMIN).first()

        for metal in self.METALS:
            obj, created = GlobalMetal.objects.get_or_create(
                name=metal["name"], symbol=metal["symbol"]
            )
            if created:
                if admin_user:
                    MaterialItem.objects.create(
                        name=metal["name"],
                        material_type=MaterialType.METAL,
                        global_metal=obj,
                        created_by=admin_user.user,
                        organization_id=admin_user.user.organization_id,
                    )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Successfully created {metal['name']} ({metal['symbol']})"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"{metal['name']} ({metal['symbol']}) already exists"
                    )
                )
