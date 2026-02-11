from __future__ import absolute_import
from __future__ import unicode_literals

import os

from celery import Celery

# set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sooq_althahab.settings")

app = Celery("sooq_althahab")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")
app.conf.timezone = "Asia/Bahrain"
app.conf.enable_utc = True

# Load task modules from all registered Django app configs.
app.autodiscover_tasks(
    [
        "sooq_althahab",
        "sooq_althahab.payment_gateway_services.credimax",
    ]
)
