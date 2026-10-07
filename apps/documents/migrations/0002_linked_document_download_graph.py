from django.db import migrations, models
import django.db.models.deletion


def set_existing_depth(apps, schema_editor):
    LinkedDocument = apps.get_model("documents", "LinkedDocument")
    LinkedDocument.objects.filter(parent__isnull=True).update(depth=1)


class Migration(migrations.Migration):
    dependencies = [("documents", "0001_initial")]
    operations = [
        migrations.AddField(
            model_name="linkeddocument",
            name="parent",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="children", to="documents.linkeddocument"),
        ),
        migrations.AddField(model_name="linkeddocument", name="final_url", field=models.URLField(blank=True, max_length=2048)),
        migrations.AddField(model_name="linkeddocument", name="depth", field=models.PositiveSmallIntegerField(db_index=True, default=0)),
        migrations.RunPython(set_existing_depth, migrations.RunPython.noop),
        migrations.AddField(model_name="linkeddocument", name="file_name", field=models.CharField(blank=True, max_length=255)),
        migrations.AddField(model_name="linkeddocument", name="content_type", field=models.CharField(blank=True, max_length=150)),
        migrations.AddField(model_name="linkeddocument", name="size_bytes", field=models.PositiveBigIntegerField(default=0)),
        migrations.AddField(model_name="linkeddocument", name="downloaded_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AlterField(
            model_name="linkeddocument",
            name="status",
            field=models.CharField(choices=[("discovered", "Discovered"), ("downloading", "Downloading"), ("downloaded", "Downloaded"), ("failed", "Failed")], db_index=True, default="discovered", max_length=20),
        ),
    ]
