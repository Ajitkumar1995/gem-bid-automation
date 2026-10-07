from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    initial = True
    dependencies = [("bids", "0001_initial")]
    operations = [
        migrations.CreateModel(name="ProcessingJob", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("task_id", models.CharField(blank=True, db_index=True, max_length=255)),
            ("status", models.CharField(choices=[("queued", "Queued"), ("running", "Running"), ("succeeded", "Succeeded"), ("failed", "Failed")], default="queued", max_length=20)),
            ("error", models.TextField(blank=True)), ("started_at", models.DateTimeField(blank=True, null=True)),
            ("completed_at", models.DateTimeField(blank=True, null=True)), ("created_at", models.DateTimeField(auto_now_add=True)),
            ("bid", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="processing_jobs", to="bids.bid")),
        ]),
        migrations.CreateModel(name="ProcessingLog", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("level", models.CharField(default="info", max_length=20)), ("message", models.TextField()),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("job", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="logs", to="processing.processingjob")),
        ]),
    ]
