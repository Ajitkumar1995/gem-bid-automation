from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class BidPreparation(models.Model):
    bid = models.OneToOneField("bids.Bid", on_delete=models.CASCADE, related_name="preparation")
    bid_number = models.CharField(max_length=120, blank=True)
    bid_title = models.CharField(max_length=255, blank=True)
    buyer_name = models.CharField(max_length=255, blank=True)
    buyer_department = models.CharField(max_length=255, blank=True)
    buyer_address = models.TextField(blank=True)
    beneficiary_details = models.TextField(blank=True)
    recipient_title = models.CharField(max_length=120, default="The Head of Department", blank=True)
    bid_date = models.DateField(null=True, blank=True)
    required_experience_years = models.PositiveSmallIntegerField(null=True, blank=True)
    bidder_turnover_threshold = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    oem_turnover_threshold = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    invoice_gstin = models.CharField(max_length=15, blank=True)
    invoice_address = models.TextField(blank=True)
    apply_mse_purchase_preference = models.BooleanField(default=False)
    payment_note = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Preparation for {self.bid}"


class BidBOQItem(models.Model):
    preparation = models.ForeignKey(BidPreparation, on_delete=models.CASCADE, related_name="boq_items")
    sort_order = models.PositiveSmallIntegerField(default=0)
    description = models.CharField(max_length=500)
    quantity = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    unit = models.CharField(max_length=60, blank=True)
    bidder_response = models.CharField(max_length=120, blank=True, default="Complied")
    source_data = models.JSONField(default=dict, blank=True)
    source_label = models.CharField(max_length=255, blank=True)
    source_key = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["preparation", "source_key"],
                condition=~models.Q(source_key=""),
                name="unique_extracted_boq_row",
            )
        ]

    def __str__(self):
        return self.description


class CustomDocumentTemplate(models.Model):
    """A reusable custom PDF template owned by one user."""
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="custom_document_templates")
    title = models.CharField(max_length=255)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title", "id"]

    def __str__(self):
        return self.title


class GeneratedDocument(models.Model):
    bid = models.ForeignKey("bids.Bid", on_delete=models.CASCADE, related_name="generated_documents")
    document_type = models.CharField(max_length=60)
    title = models.CharField(max_length=255)
    editable_content = models.TextField(blank=True)
    signature_position_x = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(100)])
    signature_position_y = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(100)])
    stamp_position_x = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(100)])
    stamp_position_y = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(100)])
    render_settings = models.JSONField(default=dict, blank=True)
    # Legacy generated files are retained for cleanup during bid retention.
    file = models.FileField(upload_to="generated/%Y/%m/", max_length=500, blank=True)
    template_version = models.CharField(max_length=20, default="1.0")
    generated_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    class Meta:
        ordering = ["-generated_at"]
        constraints = [models.UniqueConstraint(fields=["bid", "document_type"], name="unique_bid_generated_document_type")]

    def __str__(self):
        return self.title
