from django.db import transaction
from django.utils import timezone
from datetime import timedelta

from apps.documents.models import LinkedDocument
from apps.generation.models import GeneratedDocument
from apps.companies.models import CompanyDocument, CompanyProfile
from .limits import ACTIVE_BID_STATUSES
from .models import Bid, BidSystemSettings

DEFAULT_BID_RETENTION = 5


def _files_for_bid(bid):
    files = []
    for field_file in [bid.source_pdf]:
        if field_file:
            files.append((field_file.storage, field_file.name))
    for queryset in (bid.linked_documents.all(), bid.generated_documents.all()):
        for row in queryset:
            field_file = row.file
            if field_file:
                files.append((field_file.storage, field_file.name))
    return files


def _delete_unreferenced_files(files):
    for storage, name in files:
        still_used = (
            Bid.objects.filter(source_pdf=name).exists()
            or LinkedDocument.objects.filter(file=name).exists()
            or GeneratedDocument.objects.filter(file=name).exists()
            or CompanyDocument.objects.filter(file=name).exists()
            or CompanyProfile.objects.filter(signature_image=name).exists()
            or CompanyProfile.objects.filter(stamp_image=name).exists()
        )
        if name and not still_used:
            storage.delete(name)


def delete_stored_file_if_unreferenced(storage, name):
    _delete_unreferenced_files([(storage, name)])


def clear_bid_specific_data(bid):
    """Clear generated/extracted/link data while retaining the Bid row and source."""
    files = []
    for row in bid.linked_documents.all():
        if row.file:
            files.append((row.file.storage, row.file.name))
    for row in bid.generated_documents.all():
        if row.file:
            files.append((row.file.storage, row.file.name))
    bid.linked_documents.all().delete()
    bid.generated_documents.all().delete()
    bid.processing_jobs.all().delete()
    if hasattr(bid, "preparation"):
        bid.preparation.delete()
    bid.extracted_text = ""
    bid.extracted_metadata = {}
    bid.processing_error = ""
    bid.save(update_fields=["extracted_text", "extracted_metadata", "processing_error", "updated_at"])
    _delete_unreferenced_files(files)


def delete_bid_workspace(bid):
    """Delete bid-specific rows and files while preserving reusable company data."""
    with transaction.atomic():
        bid = Bid.objects.select_for_update().get(pk=bid.pk)
        files = _files_for_bid(bid)
        bid.delete()
        transaction.on_commit(lambda: _delete_unreferenced_files(files))


def expire_old_bids(now=None, user=None):
    """Remove bid workspaces older than the configurable expiry period."""
    now = now or timezone.now()
    policy = BidSystemSettings.objects.filter(pk=1).only("active_bid_expiry_days").first()
    expiry_days = policy.active_bid_expiry_days if policy else 30
    cutoff = now - timedelta(days=expiry_days)
    files = []
    expired_count = 0
    with transaction.atomic():
        expired = Bid.objects.select_for_update().filter(
            status__in=ACTIVE_BID_STATUSES,
            created_at__lt=cutoff,
        )
        if user is not None:
            expired = expired.filter(uploaded_by_id=user.pk)
        for bid in expired.iterator():
            files.extend(_files_for_bid(bid))
            bid.delete()
            expired_count += 1
        transaction.on_commit(lambda: _delete_unreferenced_files(files))
    return expired_count


def prune_user_bids(user, keep_count=None):
    """Deprecated compatibility hook; active bid creation never prunes user data."""
    return 0
