from django.db import migrations, models
from django.db.models import Q


def backfill_edges(apps, schema_editor):
    LinkedDocument = apps.get_model("documents", "LinkedDocument")
    DocumentLink = apps.get_model("documents", "DocumentLink")
    for document in LinkedDocument.objects.select_related("parent").iterator():
        source = {"source_bid_id": document.bid_id} if document.parent_id is None else {"source_document_id": document.parent_id}
        DocumentLink.objects.get_or_create(
            target_document_id=document.pk,
            page_number=document.page_number,
            **source,
            defaults={"label": document.label},
        )


class Migration(migrations.Migration):
    dependencies = [("documents", "0003_documentlink_graph")]

    operations = [
        migrations.AddField(
            model_name="documentlink",
            name="page_number",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="documentlink",
            name="label",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AlterModelOptions(
            name="documentlink",
            options={"ordering": ["page_number", "id"]},
        ),
        migrations.RunPython(backfill_edges, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="documentlink",
            constraint=models.UniqueConstraint(fields=("source_document", "target_document", "page_number"), condition=Q(source_document__isnull=False), name="unique_document_graph_edge_from_doc"),
        ),
        migrations.AddConstraint(
            model_name="documentlink",
            constraint=models.UniqueConstraint(fields=("source_bid", "target_document", "page_number"), condition=Q(source_bid__isnull=False), name="unique_document_graph_edge_from_bid"),
        ),
    ]
