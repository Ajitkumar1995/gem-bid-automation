from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    initial = True
    dependencies = [("auth", "0012_alter_user_first_name_max_length")]
    operations = [
        migrations.CreateModel(name="CompanyProfile", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("legal_name", models.CharField(max_length=255)), ("gstin", models.CharField(blank=True, max_length=15)),
            ("udyam_number", models.CharField(blank=True, max_length=30)), ("address", models.TextField(blank=True)),
            ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="company_profiles", to=settings.AUTH_USER_MODEL)),
        ], options={"ordering": ["legal_name"]}),
        migrations.CreateModel(name="CompanyDocument", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("title", models.CharField(max_length=255)), ("file", models.FileField(max_length=500, upload_to="companies/%Y/%m/")),
            ("document_type", models.CharField(blank=True, max_length=80)), ("expires_on", models.DateField(blank=True, null=True)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("company", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="documents", to="companies.companyprofile")),
        ]),
        migrations.AddConstraint(model_name="companyprofile", constraint=models.UniqueConstraint(fields=("owner", "legal_name"), name="unique_owned_company_name")),
    ]
