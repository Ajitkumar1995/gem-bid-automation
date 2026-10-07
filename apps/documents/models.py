from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

from django.db import models
from django.db.models import Q

class LinkedDocument(models.Model):
    class Status(models.TextChoices):
        DISCOVERED = "discovered", "Discovered"
        DOWNLOADING = "downloading", "Downloading"
        DOWNLOADED = "downloaded", "Downloaded"
        FAILED = "failed", "Failed"

    bid = models.ForeignKey("bids.Bid", on_delete=models.CASCADE, related_name="linked_documents")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")
    url = models.URLField(max_length=2048)
    final_url = models.URLField(max_length=2048, blank=True)
    label = models.CharField(max_length=500, blank=True)
    page_number = models.PositiveIntegerField(null=True, blank=True)
    depth = models.PositiveSmallIntegerField(default=0, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DISCOVERED, db_index=True)
    file = models.FileField(upload_to="linked/%Y/%m/", blank=True, max_length=500)
    file_name = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=150, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    downloaded_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["bid", "url"], name="unique_bid_linked_url")]

    def __str__(self):
        return self.label or self.url

    @property
    def filename(self):
        if self.file_name:
            return self.file_name
        name = PurePosixPath(unquote(urlparse(self.url).path)).name
        return name or self.label or self.url


class DocumentLink(models.Model):
    """An edge in the bid's document graph; a source may be the original bid PDF."""
    source_bid = models.ForeignKey("bids.Bid", null=True, blank=True, on_delete=models.CASCADE, related_name="document_edges")
    source_document = models.ForeignKey(
        LinkedDocument, null=True, blank=True, on_delete=models.CASCADE, related_name="outgoing_edges"
    )
    target_document = models.ForeignKey(LinkedDocument, on_delete=models.CASCADE, related_name="incoming_edges")
    page_number = models.PositiveIntegerField(null=True, blank=True)
    label = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "documents_documentlink"
        ordering = ["page_number", "id"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(source_bid__isnull=False, source_document__isnull=True) | Q(source_bid__isnull=True, source_document__isnull=False)),
                name="document_link_one_source",
            ),
            models.UniqueConstraint(
                fields=["source_document", "target_document", "page_number"],
                condition=Q(source_document__isnull=False),
                name="unique_document_graph_edge_from_doc",
            ),
            models.UniqueConstraint(
                fields=["source_bid", "target_document", "page_number"],
                condition=Q(source_bid__isnull=False),
                name="unique_document_graph_edge_from_bid",
            ),
        ]

    @property
    def bid(self):
        return self.source_bid or self.target_document.bid

    def __str__(self):
        return f"{self.source_document or self.source_bid or self.target_document.bid}: {self.target_document}"
