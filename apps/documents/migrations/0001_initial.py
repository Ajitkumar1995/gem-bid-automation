from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    initial = True
    dependencies = [("bids", "0001_initial")]
    operations = [migrations.CreateModel(name="LinkedDocument", fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("url", models.URLField(max_length=2048)), ("label", models.CharField(blank=True, max_length=500)),
        ("page_number", models.PositiveIntegerField(blank=True, null=True)),
        ("status", models.CharField(choices=[("discovered", "Discovered"), ("downloaded", "Downloaded"), ("failed", "Failed")], default="discovered", max_length=20)),
        ("file", models.FileField(blank=True, max_length=500, upload_to="linked/%Y/%m/")), ("error", models.TextField(blank=True)),
        ("created_at", models.DateTimeField(auto_now_add=True)),
        ("bid", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="linked_documents", to="bids.bid")),
    ]), migrations.AddConstraint(model_name="linkeddocument", constraint=models.UniqueConstraint(fields=("bid", "url"), name="unique_bid_linked_url"))]
