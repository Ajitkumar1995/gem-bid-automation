import hashlib
import logging
from pathlib import Path

from celery import shared_task
from django.core.files.base import ContentFile
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.bids.models import Bid
from apps.documents.models import DocumentLink, LinkedDocument
from apps.processing.models import ProcessingJob, ProcessingLog
from apps.companies.models import CompanyProfile
from apps.generation.extraction import suggested_preparation_values, sync_missing_preparation_fields
from apps.generation.models import BidPreparation
from apps.generation.boq_extraction import extract_boq_tables, import_boq_tables
from services.requirements import analyze_requirements, build_requirements_metadata
from services.documents.downloader import MAX_TOTAL_DOWNLOAD_BYTES, DownloadError, download_document
from services.documents.pdf_links import extract_pdf_links

MAX_RECURSION_DEPTH = 4
MAX_LINKED_DOCUMENTS_PER_BID = 100
logger = logging.getLogger(__name__)


def _extract_and_import_boq(bid, preparation, content, filename, content_type, job=None):
    try:
        tables = extract_boq_tables(content, filename, content_type)
        return import_boq_tables(preparation, tables)
    except Exception as exc:
        logger.exception("Could not extract BoQ data from %s for bid %s", filename, bid.pk)
        if job:
            ProcessingLog.objects.create(
                job=job,
                level="warning",
                message=f"Could not extract BoQ data from {filename}: {exc.__class__.__name__}.",
            )
        return 0


def _enqueue_link(link):
    job = ProcessingJob.objects.create(bid=link.bid)
    task = process_linked_document.delay(link.pk, job.pk)
    job.task_id = task.id
    job.save(update_fields=["task_id"])


def _discover_child_links(parent, content, base_url):
    if parent.depth >= MAX_RECURSION_DEPTH:
        return 0
    try:
        extracted = extract_pdf_links(content, base_url=base_url)
    except Exception as exc:
        job = parent.bid.processing_jobs.order_by("-created_at").first()
        if job:
            ProcessingLog.objects.create(
                job=job,
                level="warning",
                message=f"Could not inspect linked PDF {parent.filename}: {exc.__class__.__name__}.",
            )
        return 0

    queued = 0
    for item in extracted:
        if parent.bid.linked_documents.count() >= MAX_LINKED_DOCUMENTS_PER_BID:
            break
        try:
            with transaction.atomic():
                child, created = LinkedDocument.objects.get_or_create(
                    bid=parent.bid,
                    url=item["url"],
                    defaults={
                        "parent": parent,
                        "depth": parent.depth + 1,
                        "page_number": item["page_number"],
                        "label": item["label"],
                    },
                )
        except IntegrityError:
            continue
        edge_query = DocumentLink.objects.filter(
            source_bid__isnull=True,
            source_document=parent,
            target_document=child,
            page_number=item["page_number"],
        )
        if not edge_query.exists():
            DocumentLink.objects.create(
                source_bid=None,
                source_document=parent,
                target_document=child,
                page_number=item["page_number"],
                label=item["label"],
            )
        if created:
            _enqueue_link(child)
            queued += 1
    return queued


@shared_task(bind=True, autoretry_for=(OSError, OperationalError), retry_backoff=True, max_retries=5)
def extract_bid_pdf(self, bid_id):
    bid = Bid.objects.filter(pk=bid_id).first()
    if not bid:
        return "deleted"
    job = ProcessingJob.objects.filter(bid=bid).order_by("-created_at").first()
    if job:
        job.status = ProcessingJob.Status.RUNNING
        job.started_at = timezone.now()
        job.save(update_fields=["status", "started_at"])
    try:
        import pymupdf

        with bid.source_pdf.open("rb") as pdf:
            raw_pdf = pdf.read()
        with pymupdf.open(stream=raw_pdf, filetype="pdf") as document:
            page_text = [page.get_text() for page in document]
            metadata = dict(document.metadata or {})
        extracted_text = "\n\n".join(page_text)
        if extracted_text.strip():
            metadata["first_page_text"] = page_text[0] if page_text else ""
            profile = CompanyProfile.objects.filter(owner=bid.uploaded_by).first()
            analysis = analyze_requirements(extracted_text)
            metadata["requirements_analysis"] = build_requirements_metadata(extracted_text, profile)
            bid_analysis = analysis.bid_analysis
            if not bid.bid_number and bid_analysis.get("bid_number"):
                bid.bid_number = str(bid_analysis["bid_number"])[:120]
            if not bid.title and (bid_analysis.get("item_name") or bid_analysis.get("title")):
                bid.title = str(bid_analysis.get("item_name") or bid_analysis.get("title"))[:255]
        for item in extract_pdf_links(raw_pdf):
            link, created = LinkedDocument.objects.get_or_create(
                bid=bid,
                url=item["url"],
                defaults={"page_number": item["page_number"], "label": item["label"], "depth": 1},
            )
            if not created and not link.label and item["label"]:
                link.label = item["label"]
                link.page_number = link.page_number or item["page_number"]
                if not link.parent:
                    link.depth = 1
                link.save(update_fields=["label", "page_number", "depth"])
            edge_query = DocumentLink.objects.filter(
                source_bid=bid,
                source_document__isnull=True,
                target_document=link,
                page_number=item["page_number"],
            )
            if not edge_query.exists():
                DocumentLink.objects.create(
                    source_bid=bid,
                    target_document=link,
                    page_number=item["page_number"],
                    label=item["label"],
                )

        bid.extracted_text = extracted_text
        bid.extracted_metadata = metadata
        # Use the same local PDF field mapping as the preparation form. This
        # also extracts a GeM number and labels directly from text.
        extracted_fields = suggested_preparation_values(bid)
        if not bid.bid_number and extracted_fields["bid_number"]:
            bid.bid_number = extracted_fields["bid_number"]
        if not bid.title and extracted_fields["bid_title"]:
            bid.title = extracted_fields["bid_title"]
        updated = Bid.objects.filter(pk=bid_id).update(
            bid_number=bid.bid_number,
            title=bid.title,
            extracted_text=extracted_text,
            extracted_metadata=metadata,
            status=Bid.Status.READY,
            processing_error="",
            updated_at=timezone.now(),
        )
        if not updated:
            return "deleted"
        sync_missing_preparation_fields(bid)
        preparation = BidPreparation.objects.filter(bid_id=bid_id).first()
        imported_boq_rows = (
            _extract_and_import_boq(
                bid,
                preparation,
                raw_pdf,
                bid.source_filename,
                "application/pdf",
                job,
            )
            if preparation
            else 0
        )
        if job:
            job_update = ProcessingJob.objects.filter(pk=job.pk).update(status=ProcessingJob.Status.SUCCEEDED, completed_at=timezone.now())
            if job_update:
                ProcessingLog.objects.create(
                    job_id=job.pk,
                    message=f"Extracted {len(page_text)} pages, imported {imported_boq_rows} BoQ rows, and discovered {bid.linked_documents.count()} links.",
                )
        for link in bid.linked_documents.filter(depth=1, status=LinkedDocument.Status.DISCOVERED)[:MAX_LINKED_DOCUMENTS_PER_BID]:
            _enqueue_link(link)
    except Exception as exc:
        updated = Bid.objects.filter(pk=bid_id).update(
            status=Bid.Status.FAILED,
            processing_error=str(exc)[:4000],
            updated_at=timezone.now(),
        )
        if not updated:
            return "deleted"
        if job:
            job_update = ProcessingJob.objects.filter(pk=job.pk).update(
                status=ProcessingJob.Status.FAILED,
                error=str(exc)[:4000],
                completed_at=timezone.now(),
            )
            if job_update:
                ProcessingLog.objects.create(job_id=job.pk, level="error", message=str(exc)[:4000])
        raise


@shared_task
def cleanup_expired_bids():
    """Scheduled cleanup for expired bid workspaces and their temporary files."""
    from apps.bids.retention import expire_old_bids

    return expire_old_bids()


@shared_task(bind=True, autoretry_for=(OSError, OperationalError), retry_backoff=True, max_retries=5)
def process_linked_document(self, document_id, job_id):
    """Download one discovered file, then queue any PDF links it contains."""
    with transaction.atomic():
        document = LinkedDocument.objects.select_for_update().select_related("bid").filter(pk=document_id).first()
        if not document:
            return "deleted"
        retrying_interrupted_task = (
            self.request.retries > 0
            and document.status in {LinkedDocument.Status.DOWNLOADING, LinkedDocument.Status.FAILED}
        )
        if document.status != LinkedDocument.Status.DISCOVERED and not retrying_interrupted_task:
            return document.status
        document.status = LinkedDocument.Status.DOWNLOADING
        document.error = ""
        document.save(update_fields=["status", "error"])
    job = ProcessingJob.objects.get(pk=job_id)
    job.status = ProcessingJob.Status.RUNNING
    job.started_at = timezone.now()
    job.save(update_fields=["status", "started_at"])

    try:
        downloaded = download_document(document.url)
        if downloaded.content.startswith(b"%PDF-"):
            downloaded.content_type = "application/pdf"
        current_total = document.bid.linked_documents.exclude(pk=document.pk).aggregate(total=Sum("size_bytes"))["total"] or 0
        if current_total + len(downloaded.content) > MAX_TOTAL_DOWNLOAD_BYTES:
            raise DownloadError("The bid's 250 MB total linked-document download limit has been reached.")
        digest = hashlib.sha256(downloaded.content).digest()
        existing_copy = None
        candidates = LinkedDocument.objects.exclude(pk=document.pk).filter(size_bytes=len(downloaded.content)).exclude(file="")
        for candidate in candidates.iterator():
            try:
                with candidate.file.open("rb") as existing:
                    existing_digest = hashlib.sha256()
                    for chunk in iter(lambda: existing.read(1024 * 1024), b""):
                        existing_digest.update(chunk)
                if existing_digest.digest() == digest:
                    existing_copy = candidate.file.name
                    break
            except (FileNotFoundError, OSError):
                continue
        if existing_copy:
            # Share identical downloaded content instead of creating another
            # collision-suffixed physical copy.
            document.file.name = existing_copy
        else:
            document.file.save(downloaded.filename, ContentFile(downloaded.content), save=False)
        document.file_name = downloaded.filename
        document.content_type = downloaded.content_type
        document.size_bytes = len(downloaded.content)
        document.final_url = downloaded.final_url
        document.downloaded_at = timezone.now()
        document.status = LinkedDocument.Status.DOWNLOADED
        document.error = ""
        document.save()

        is_pdf = downloaded.content.startswith(b"%PDF-") or downloaded.content_type == "application/pdf" or Path(downloaded.filename).suffix.lower() == ".pdf"
        preparation = BidPreparation.objects.filter(bid_id=document.bid_id).first()
        imported_boq_rows = (
            _extract_and_import_boq(
                document.bid,
                preparation,
                downloaded.content,
                downloaded.filename or document.label or "linked-document",
                downloaded.content_type,
                job,
            )
            if preparation
            else 0
        )
        queued_children = _discover_child_links(document, downloaded.content, downloaded.final_url) if is_pdf else 0
        job.status = ProcessingJob.Status.SUCCEEDED
        job.completed_at = timezone.now()
        job.save(update_fields=["status", "completed_at"])
        ProcessingLog.objects.create(
            job=job,
            message=f"Downloaded {document.filename} ({document.size_bytes} bytes); imported {imported_boq_rows} BoQ rows and queued {queued_children} child links.",
        )
        return document.status
    except DownloadError as exc:
        document.status = LinkedDocument.Status.FAILED
        document.error = str(exc)[:2000]
        document.save(update_fields=["status", "error"])
        job.status = ProcessingJob.Status.FAILED
        job.error = document.error
        job.completed_at = timezone.now()
        job.save(update_fields=["status", "error", "completed_at"])
        ProcessingLog.objects.create(job=job, level="error", message=document.error)
        return document.status
    except Exception as exc:
        document.status = LinkedDocument.Status.FAILED
        document.error = f"Processing failed: {exc.__class__.__name__}."
        document.save(update_fields=["status", "error"])
        job.status = ProcessingJob.Status.FAILED
        job.error = document.error
        job.completed_at = timezone.now()
        job.save(update_fields=["status", "error", "completed_at"])
        ProcessingLog.objects.create(job=job, level="error", message=document.error)
        raise
