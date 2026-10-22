from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("generation", "0007_alter_bidboqitem_bidder_response"),
    ]

    operations = [
        migrations.AddField(
            model_name="generateddocument",
            name="render_settings",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
