from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    initial = True
    dependencies = [("auth", "0012_alter_user_first_name_max_length")]
    operations = [migrations.CreateModel(name="Bid", fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("title", models.CharField(blank=True, max_length=255)), ("bid_number", models.CharField(blank=True, db_index=True, max_length=120)),
        ("source", models.CharField(default="GeM", max_length=40)),
        ("source_pdf", models.FileField(max_length=500, upload_to="bids/%Y/%m/")),
        ("status", models.CharField(choices=[("uploaded", "Uploaded"), ("processing", "Processing"), ("ready", "Ready for review"), ("failed", "Failed")], db_index=True, default="uploaded", max_length=20)),
        ("extracted_text", models.TextField(blank=True)), ("extracted_metadata", models.JSONField(blank=True, default=dict)),
        ("processing_error", models.TextField(blank=True)), ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
        ("updated_at", models.DateTimeField(auto_now=True)),
        ("uploaded_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="bids", to=settings.AUTH_USER_MODEL)),
    ], options={"ordering": ["-created_at"]})]
