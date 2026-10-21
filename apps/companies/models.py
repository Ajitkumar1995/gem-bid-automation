from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


def default_signature_document_types():
    return ["experience_declaration", "past_performance", "bidder_turnover", "additional_doc_1", "additional_doc_2", "atc_certificate", "boq_specifications", "oem_annual_turnover"]


class CompanyProfile(models.Model):
    class EnterpriseType(models.TextChoices):
        MICRO = "micro", "Micro"
        SMALL = "small", "Small"
        MEDIUM = "medium", "Medium"
        OTHER = "other", "Other / not registered as MSME"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="company_profiles")
    legal_name = models.CharField(max_length=255, blank=True)
    trade_name = models.CharField(max_length=255, blank=True)
    constitution = models.CharField(max_length=120, blank=True)
    pan = models.CharField(max_length=10, blank=True)
    gstin = models.CharField(max_length=15, blank=True)
    udyam_number = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=120, blank=True)
    pincode = models.CharField(max_length=10, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    signatory_name = models.CharField(max_length=255, blank=True)
    signatory_designation = models.CharField(max_length=120, blank=True)
    signature_image = models.ImageField(upload_to="companies/signatures/%Y/%m/", blank=True)
    stamp_image = models.ImageField(upload_to="companies/stamps/%Y/%m/", blank=True)
    signature_style = models.CharField(max_length=20, choices=[("blue_ink", "Blue ink (sample format)"), ("black_ink", "Black ink")], default="blue_ink")
    signature_rotation = models.DecimalField(max_digits=4, decimal_places=1, default=0, validators=[MinValueValidator(-90), MaxValueValidator(90)])
    signature_scale = models.DecimalField(max_digits=3, decimal_places=2, default=1, validators=[MinValueValidator(0.5), MaxValueValidator(1.5)])
    signature_position_x = models.DecimalField(max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    signature_position_y = models.DecimalField(max_digits=5, decimal_places=2, default=50, validators=[MinValueValidator(0), MaxValueValidator(100)])
    stamp_rotation = models.DecimalField(max_digits=4, decimal_places=1, default=0, validators=[MinValueValidator(-90), MaxValueValidator(90)])
    stamp_scale = models.DecimalField(max_digits=3, decimal_places=2, default=1, validators=[MinValueValidator(0.5), MaxValueValidator(1.5)])
    stamp_position_x = models.DecimalField(max_digits=5, decimal_places=2, default=77, validators=[MinValueValidator(0), MaxValueValidator(100)])
    stamp_position_y = models.DecimalField(max_digits=5, decimal_places=2, default=50, validators=[MinValueValidator(0), MaxValueValidator(100)])
    signature_document_types = models.JSONField(default=default_signature_document_types, blank=True)
    is_msme = models.BooleanField(default=False)
    enterprise_type = models.CharField(max_length=12, choices=EnterpriseType.choices, default=EnterpriseType.OTHER)
    is_startup = models.BooleanField(default=False)
    startup_recognition_number = models.CharField(max_length=80, blank=True)
    business_activity = models.CharField(max_length=255, blank=True)
    professional_experience_years = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    professional_experience_summary = models.TextField(blank=True)
    oem_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["legal_name"]
        constraints = [models.UniqueConstraint(fields=["owner", "legal_name"], name="unique_owned_company_name")]

    def __str__(self):
        return self.legal_name

class CompanyDocument(models.Model):
    class DocumentType(models.TextChoices):
        UDYAM = "udyam", "Udyam / MSME certificate"
        GST = "gst", "GST certificate"
        PAN = "pan", "PAN document"
        ITR = "itr", "ITR / turnover evidence"
        EXPERIENCE = "experience", "Experience / past performance proof"
        OEM = "oem", "OEM authorization / turnover evidence"
        OTHER = "other", "Other supporting document"

    company = models.ForeignKey(CompanyProfile, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=255)
    file = models.FileField(upload_to="companies/%Y/%m/", max_length=500)
    include_signature = models.BooleanField(default=True)
    include_stamp = models.BooleanField(default=False)
    document_type = models.CharField(max_length=80, choices=DocumentType.choices, default=DocumentType.OTHER)
    entity_name = models.CharField(max_length=255, blank=True, help_text="OEM or legal entity named by this evidence, if different from the profile.")
    assessment_year = models.CharField(max_length=9, blank=True)
    expires_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
