from pathlib import Path

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

class Bid(models.Model):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready for review"
        FAILED = "failed", "Failed"

    title = models.CharField(max_length=255, blank=True)
    bid_number = models.CharField(max_length=120, blank=True, db_index=True)
    source = models.CharField(max_length=40, default="GeM")
    source_pdf = models.FileField(upload_to="bids/%Y/%m/", max_length=500)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bids")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPLOADED, db_index=True)
    extracted_text = models.TextField(blank=True)
    extracted_metadata = models.JSONField(default=dict, blank=True)
    processing_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or self.bid_number or f"Bid {self.pk or 'new'}"

    @property
    def source_filename(self):
        return Path(self.source_pdf.name).name if self.source_pdf else ""


class BidRetentionPolicy(models.Model):
    """Per-account active bid limit override, managed only by site administrators."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bid_retention_policy")
    bid_limit = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(500)],
        help_text="Leave blank to use the site-wide default active bid limit.",
    )
    max_saved_bids = models.PositiveSmallIntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(500)],
        help_text="Legacy setting retained for compatibility; new bid creation uses Bid limit.",
    )

    class Meta:
        verbose_name = "Bid retention policy"
        verbose_name_plural = "Bid retention policies"

    def __str__(self):
        return f"Bid limit for {self.user}: {self.bid_limit or 'default'}"


class BidSystemSettings(models.Model):
    """Singleton settings for default bid limits and temporary bid lifetime."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    default_bid_limit = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(500)],
    )
    active_bid_expiry_days = models.PositiveSmallIntegerField(
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(3650)],
        help_text="Delete active bid workspaces after this many days since creation.",
    )

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return "GeM bid system settings"


class BidCreationLock(models.Model):
    """A per-user row to serialize bid-limit checks on all supported databases."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bid_creation_lock")
    lock_version = models.PositiveIntegerField(default=0)


class BidLimitAudit(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bid_limit_changes")
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="changed_bid_limits")
    old_limit = models.PositiveSmallIntegerField()
    new_limit = models.PositiveSmallIntegerField()
    reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user}: {self.old_limit} → {self.new_limit}"
