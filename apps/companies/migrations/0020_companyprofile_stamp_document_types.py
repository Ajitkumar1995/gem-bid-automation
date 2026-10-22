import apps.companies.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("companies", "0019_enable_signatures_for_all_builtin_pdfs"),
    ]

    operations = [
        migrations.AddField(
            model_name="companyprofile",
            name="stamp_document_types",
            field=models.JSONField(blank=True, default=apps.companies.models.default_stamp_document_types),
        ),
    ]
