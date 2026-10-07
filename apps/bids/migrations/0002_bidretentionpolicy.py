from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("bids", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="BidRetentionPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("max_saved_bids", models.PositiveSmallIntegerField(default=5, help_text="Maximum recent GeM bids to retain for this account (1–500). Older bid data and bid-specific files are removed after uploads.", validators=[MinValueValidator(1), MaxValueValidator(500)])),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="bid_retention_policy", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "Bid retention policy", "verbose_name_plural": "Bid retention policies"},
        ),
    ]
