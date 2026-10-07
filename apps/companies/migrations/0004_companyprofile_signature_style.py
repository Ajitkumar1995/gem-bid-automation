from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("companies", "0003_companyprofile_signature_image")]
    operations = [migrations.AddField(
        model_name="companyprofile",
        name="signature_style",
        field=models.CharField(choices=[("original", "Original"), ("angled", "Blue ink, angled like the sample"), ("compact", "Compact")], default="original", max_length=20),
    )]
