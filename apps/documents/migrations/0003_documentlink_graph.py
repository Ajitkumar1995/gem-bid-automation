from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


class CreateModelIfMissing(migrations.CreateModel):
    """Adopt an existing document_edges table without replacing user data."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        table = to_state.apps.get_model(app_label, self.name)._meta.db_table
        if table in schema_editor.connection.introspection.table_names():
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        # This model may have existed before this migration and can contain user data.
        return


class Migration(migrations.Migration):
    dependencies = [("documents", "0002_linked_document_download_graph")]

    operations = [
        CreateModelIfMissing(
            name="DocumentLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("source_bid", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="document_edges", to="bids.bid")),
                ("source_document", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="outgoing_edges", to="documents.linkeddocument")),
                ("target_document", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="incoming_edges", to="documents.linkeddocument")),
            ],
            options={
                "db_table": "documents_documentlink",
                "constraints": [models.CheckConstraint(condition=Q(source_bid__isnull=False, source_document__isnull=True) | Q(source_bid__isnull=True, source_document__isnull=False), name="document_link_one_source")],
            },
        ),
    ]
