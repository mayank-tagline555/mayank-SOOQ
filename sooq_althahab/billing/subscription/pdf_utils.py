from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from weasyprint import CSS
from weasyprint import HTML


def render_subscription_invoice_pdf(template_name, context):
    context["is_pdf"] = True
    html = render_to_string(template_name, context)

    pdf_io = BytesIO()

    static_dir = Path(settings.BASE_DIR) / "static"
    base_url = static_dir.resolve().as_uri()
    css_path = static_dir / "css/pdf_style.css"

    HTML(string=html, base_url=base_url).write_pdf(
        pdf_io,
        stylesheets=[CSS(filename=css_path)],
    )

    pdf_io.seek(0)
    return pdf_io
