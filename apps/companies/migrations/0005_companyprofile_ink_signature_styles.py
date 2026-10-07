from django.db import migrations, models


def remap_styles(apps, schema_editor):
    Profile = apps.get_model("companies", "CompanyProfile")
    Profile.objects.filter(signature_style="original").update(signature_style="blue_ink")
    Profile.objects.filter(signature_style="angled").update(signature_style="blue_angled")
    Profile.objects.filter(signature_style="compact").update(signature_style="black_ink")


class Migration(migrations.Migration):
    dependencies = [("companies", "0004_companyprofile_signature_style")]
    operations = [
        migrations.RunPython(remap_styles, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="companyprofile",
            name="signature_style",
            field=models.CharField(
                choices=[("blue_ink", "Blue ink"), ("black_ink", "Black ink"), ("blue_angled", "Blue ink, angled like the sample")],
                default="blue_ink",
                max_length=20,
            ),
        ),
    ]
