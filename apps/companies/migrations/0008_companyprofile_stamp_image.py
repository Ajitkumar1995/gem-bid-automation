from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("companies", "0007_signature_editor_and_pdf_choices")]
    operations = [
        migrations.AddField(
            model_name="companyprofile",
            name="stamp_image",
            field=models.ImageField(blank=True, upload_to="companies/stamps/%Y/%m/"),
        ),
    ]
