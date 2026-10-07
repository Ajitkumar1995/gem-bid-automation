from django.db import migrations, models
import django.core.validators


def update_unchanged_default_positions(apps, schema_editor):
    CompanyProfile = apps.get_model("companies", "CompanyProfile")
    CompanyProfile.objects.filter(
        signature_position_x=28,
        signature_position_y=50,
    ).update(signature_position_x=0)
    CompanyProfile.objects.filter(
        stamp_position_x=50,
        stamp_position_y=50,
    ).update(stamp_position_x=77)


class Migration(migrations.Migration):

    dependencies = [
        ("companies", "0016_companydocument_include_stamp"),
    ]

    operations = [
        migrations.RunPython(update_unchanged_default_positions, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="companyprofile",
            name="signature_position_x",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=5,
                validators=[
                    django.core.validators.MinValueValidator(0),
                    django.core.validators.MaxValueValidator(100),
                ],
            ),
        ),
        migrations.AlterField(
            model_name="companyprofile",
            name="stamp_position_x",
            field=models.DecimalField(
                decimal_places=2,
                default=77,
                max_digits=5,
                validators=[
                    django.core.validators.MinValueValidator(0),
                    django.core.validators.MaxValueValidator(100),
                ],
            ),
        ),
    ]
