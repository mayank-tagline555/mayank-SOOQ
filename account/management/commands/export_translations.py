import os

import openpyxl
import polib
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Export translation texts (English & Arabic) from .po files to an Excel file"

    def handle(self, *args, **kwargs):
        locale_path = os.path.join(
            settings.BASE_DIR, "locale", "ar", "LC_MESSAGES", "django.po"
        )
        excel_output_path = os.path.join(settings.BASE_DIR, "translations.xlsx")

        if not os.path.exists(locale_path):
            self.stderr.write(
                self.style.ERROR(f"Translation file not found: {locale_path}")
            )
            return

        self.stdout.write(self.style.NOTICE("Reading translation file..."))

        # Load .po file
        po = polib.pofile(locale_path)

        # Extract translations
        data = [["English", "Arabic"]] + [
            [entry.msgid, entry.msgstr] for entry in po if entry.msgid and entry.msgstr
        ]

        if len(data) == 1:  # Only headers, no actual translations
            self.stdout.write(
                self.style.WARNING("No translations found in the .po file.")
            )
            return

        # Create an Excel file using openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Translations"

        for row in data:
            ws.append(row)

        os.makedirs(os.path.dirname(excel_output_path), exist_ok=True)
        wb.save(excel_output_path)

        self.stdout.write(
            self.style.SUCCESS(f"Translation file created: {excel_output_path}")
        )
