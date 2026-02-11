from django.db import models


class ManufactureRequestStatus(models.TextChoices):
    """Represents the possible statuses for a correction value."""

    PENDING = "PENDING", "Pending"
    ACCEPTED = "ACCEPTED", "Accepted"
    REJECTED = "REJECTED", "Rejected"
