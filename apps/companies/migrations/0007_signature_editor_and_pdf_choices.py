import apps.companies.models
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("companies", "0006_signature_style_sample_ink")]
    operations = [
        migrations.AddField(
            model_name="companyprofile",
            name="signature_rotation",
            field=models.DecimalField(default=0, decimal_places=1, max_digits=4, validators=[MinValueValidator(-45), MaxValueValidator(45)]),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="signature_scale",
            field=models.DecimalField(default=1, decimal_places=2, max_digits=3, validators=[MinValueValidator(0.5), MaxValueValidator(1.5)]),
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="signature_document_types",
            field=models.JSONField(blank=True, default=apps.companies.models.default_signature_document_types),
        ),
        migrations.AddField(
            model_name="companydocument",
            name="include_signature",
            field=models.BooleanField(default=True),
        ),
    ]
