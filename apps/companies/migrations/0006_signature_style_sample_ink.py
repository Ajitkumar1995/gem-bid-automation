from django.db import migrations, models


def normalize_styles(apps, schema_editor):
    Profile = apps.get_model("companies", "CompanyProfile")
    Profile.objects.filter(signature_style="blue_angled").update(signature_style="blue_ink")


class Migration(migrations.Migration):
    dependencies = [("companies", "0005_companyprofile_ink_signature_styles")]
    operations = [
        migrations.RunPython(normalize_styles, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="companyprofile",
            name="signature_style",
            field=models.CharField(
                choices=[("blue_ink", "Blue ink (sample format)"), ("black_ink", "Black ink")],
                default="blue_ink",
                max_length=20,
            ),
        ),
    ]
