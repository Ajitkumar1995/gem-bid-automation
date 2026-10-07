from django.contrib.auth.decorators import login_required
from django.db import OperationalError, transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.contrib import messages
from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from apps.documents.models import LinkedDocument
from apps.processing.models import ProcessingJob
from .limits import bid_limit_message, get_active_bid_count, get_effective_bid_limit, lock_user_bid_slots, user_bid_creation_guard
from .models import Bid
from .serializers import BidSerializer

class BidViewSet(viewsets.ModelViewSet):
    serializer_class = BidSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filterset_fields = ["status", "source"]
    search_fields = ["title", "bid_number"]
    ordering_fields = ["created_at", "updated_at", "title"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Bid.objects.none()
        return Bid.objects.filter(uploaded_by=self.request.user).prefetch_related("linked_documents")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        try:
            with user_bid_creation_guard(user):
                with transaction.atomic():
                    lock_user_bid_slots(user)
                    limit = get_effective_bid_limit(user)
                    active_count = get_active_bid_count(user)
                    if active_count >= limit:
                        return Response(
                            {
                                "success": False,
                                "error": "BID_LIMIT_REACHED",
                                "message": bid_limit_message(limit),
                            },
                            status=status.HTTP_409_CONFLICT,
                        )
                    self.perform_create(serializer)
        except OperationalError:
            # On SQLite, concurrent writers may fail to acquire its database
            # write lock. Report the same safe limit response after the winner
            # commits instead of surfacing a server error.
            limit = get_effective_bid_limit(user)
            try:
                active_count = get_active_bid_count(user)
            except OperationalError:
                return Response(
                    {
                        "success": False,
                        "error": "BID_LIMIT_CHECK_BUSY",
                        "message": "The bid limit is being checked by another request. Please try again shortly.",
                    },
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            if active_count >= limit:
                return Response(
                    {"success": False, "error": "BID_LIMIT_REACHED", "message": bid_limit_message(limit)},
                    status=status.HTTP_409_CONFLICT,
                )
            raise
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        user = self.request.user
        bid = serializer.save(uploaded_by=user, status=Bid.Status.PROCESSING)
        from apps.bids.tasks import extract_bid_pdf
        job = ProcessingJob.objects.create(bid=bid)
        def enqueue_extraction():
            task = extract_bid_pdf.delay(bid.pk)
            ProcessingJob.objects.filter(pk=job.pk).update(task_id=task.id)
        transaction.on_commit(enqueue_extraction)

    def perform_destroy(self, instance):
        from .retention import delete_bid_workspace
        delete_bid_workspace(instance)

@login_required
def bid_dashboard(request):
    from .retention import expire_old_bids
    expire_old_bids(user=request.user)
    bids = Bid.objects.filter(uploaded_by=request.user).prefetch_related("linked_documents", "generated_documents")
    active_count = get_active_bid_count(request.user)
    bid_limit = get_effective_bid_limit(request.user)
    return render(request, "bids/dashboard.html", {
        "bids": bids,
        "active_bid_count": active_count,
        "active_bid_limit": bid_limit,
        "bid_limit_reached": active_count >= bid_limit,
    })


@login_required
@require_POST
def complete_bid(request, bid_id):
    bid = get_object_or_404(Bid, pk=bid_id, uploaded_by=request.user)
    from .retention import delete_bid_workspace
    action = request.POST.get("action", "complete")
    delete_bid_workspace(bid)
    if action == "delete":
        messages.success(request, "Bid deleted and temporary bid data cleared. Your company profile and reusable documents were kept.")
    else:
        messages.success(request, "Bid completed and temporary bid data deleted. Your company profile and reusable documents were kept.")
    return redirect("bid-dashboard")


@login_required
def bid_link_list(request, bid_id):
    bid = Bid.objects.prefetch_related("linked_documents").filter(
        pk=bid_id,
        uploaded_by=request.user,
    ).first()
    if bid is None:
        messages.warning(
            request,
            "That bid is no longer available. It may have been completed, deleted, or expired. Check your active bids.",
        )
        return redirect("bid-dashboard")
    links = bid.linked_documents.select_related("parent").prefetch_related("incoming_edges__source_document").order_by("depth", "created_at")
    pending_downloads = links.filter(status__in=[LinkedDocument.Status.DISCOVERED, LinkedDocument.Status.DOWNLOADING]).exists()
    retryable_links = links.filter(status__in=[LinkedDocument.Status.DISCOVERED, LinkedDocument.Status.FAILED]).exists()
    return render(request, "bids/links.html", {"bid": bid, "links": links, "pending_downloads": pending_downloads, "retryable_links": retryable_links})


@login_required
@require_POST
def queue_bid_links(request, bid_id):
    bid = get_object_or_404(Bid, pk=bid_id, uploaded_by=request.user)
    from apps.bids.tasks import MAX_LINKED_DOCUMENTS_PER_BID, MAX_RECURSION_DEPTH, _enqueue_link

    links = bid.linked_documents.filter(
        status__in=[LinkedDocument.Status.DISCOVERED, LinkedDocument.Status.FAILED],
        depth__lte=MAX_RECURSION_DEPTH,
    ).order_by("depth", "created_at")[:MAX_LINKED_DOCUMENTS_PER_BID]
    for link in links:
        if link.status == LinkedDocument.Status.FAILED:
            link.status = LinkedDocument.Status.DISCOVERED
            link.error = ""
            link.save(update_fields=["status", "error"])
        _enqueue_link(link)
    return redirect("bid-link-list", bid_id=bid.pk)


@login_required
def view_bid_pdf(request, bid_id):
    bid = get_object_or_404(Bid, pk=bid_id, uploaded_by=request.user)
    if not bid.source_pdf:
        raise Http404("Bid PDF not found.")
    try:
        bid.source_pdf.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("Bid PDF not found.")
    filename = bid.source_filename
    response = FileResponse(bid.source_pdf, content_type="application/pdf", as_attachment=False, filename=filename)
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
def view_linked_file(request, bid_id, document_id):
    document = get_object_or_404(
        LinkedDocument,
        pk=document_id,
        bid_id=bid_id,
        bid__uploaded_by=request.user,
        status=LinkedDocument.Status.DOWNLOADED,
    )
    try:
        document.file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("Downloaded document not found.")
    is_pdf = document.content_type == "application/pdf" or document.filename.lower().endswith(".pdf")
    response = FileResponse(
        document.file,
        content_type=document.content_type or "application/octet-stream",
        as_attachment=not is_pdf,
        filename=document.filename,
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response
