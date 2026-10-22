from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("generation", "0007_alter_bidboqitem_bidder_response"),
    ]

    operations = [
        migrations.AddField(
            model_name="bidpreparation",
            name="beneficiary_details",
            field=models.TextField(blank=True),
        ),
    ]
