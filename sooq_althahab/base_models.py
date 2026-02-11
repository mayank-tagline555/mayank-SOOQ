from django.db import models
from django.utils import timezone


class TimeStampedModelMixin(models.Model):
    """
    A Django model mixin that provides automatic timestamp fields.

    Attributes:
        created_at (DateTimeField): The date and time when the record was first created.
        updated_at (DateTimeField): The date and time when the record was last modified.

    Meta:
        abstract (bool): Indicates that this model is abstract and should not be used to create any database table.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # If this is not a new object, update the updated_at
        if self.pk:
            self.updated_at = timezone.now()
        super().save(*args, **kwargs)

    class Meta:
        abstract = True


class UserTimeStampedModelMixin(TimeStampedModelMixin):
    """
    A mixin that extends TimeStampedModelMixin to include user tracking.

    This mixin adds two additional fields to track the user who created and last updated a record:
    - `created_by`: A ForeignKey to the user who created the record.
    - `updated_by`: A ForeignKey to the user who last updated the record.

    The ForeignKey references the user model specified by `settings.AUTH_USER_MODEL`,
    ensuring compatibility with custom user models.

    Attributes:
        created_by (ForeignKey): The user who created the record.
        updated_by (ForeignKey): The user who last updated the record.

    Meta:
        abstract (bool): Indicates that this model is abstract and should not be used to create any database table.
    """

    created_by = models.ForeignKey(
        "account.User",
        on_delete=models.CASCADE,
        related_name="created_by%(class)s",
    )
    updated_by = models.ForeignKey(
        "account.User",
        on_delete=models.CASCADE,
        related_name="updated_by_%(class)s",
        null=True,
        blank=True,
    )

    class Meta:
        abstract = True


class OwnershipMixin(models.Model):
    """
    A mixin that provides fields to track the ownership of a record.

    Attributes:
        organization_id (ForeignKey): The organization that owns the record.

    Meta:
        abstract (bool): Indicates that this model is abstract and should not be used to create any database table.
    """

    organization_id = models.ForeignKey(
        "account.Organization",
        db_index=True,
        on_delete=models.PROTECT,
        related_name="%(class)s",
    )

    class Meta:
        abstract = True
