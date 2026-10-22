from pathlib import Path
import hashlib
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from .forms import CompanyDocumentForm, CompanyProfileForm, CompanySignatureForm
from .models import CompanyDocument, CompanyProfile


def _same_upload_as_saved(upload, field_file):
    """Return True when a submitted image already matches the saved image."""
    if not upload or not field_file:
        return False
    digest = hashlib.sha256()
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    existing = hashlib.sha256()
    try:
        with field_file.open("rb") as saved:
            for chunk in iter(lambda: saved.read(1024 * 1024), b""):
                existing.update(chunk)
    except (FileNotFoundError, OSError):
        return False
    return digest.digest() == existing.digest()


@login_required
def company_profile(request):
    profile = CompanyProfile.objects.filter(owner=request.user).first()
    if request.method == "POST":
        form_action = request.POST.get("form_action")
        if form_action == "signature":
            if not profile:
                profile = CompanyProfile.objects.create(owner=request.user)
            upload_files = request.FILES.copy()
            # Re-saving the same stamp/signature needlessly creates a new
            # collision-suffixed file every time Django receives it.
            for field_name in ("signature_image", "stamp_image"):
                if _same_upload_as_saved(upload_files.get(field_name), getattr(profile, field_name)):
                    upload_files.pop(field_name, None)
            signature_form = CompanySignatureForm(request.POST, upload_files, instance=profile)
            profile_form = CompanyProfileForm(instance=profile)
            document_form = CompanyDocumentForm()
            if signature_form.is_valid():
                old_signature = profile.signature_image.name if profile.signature_image else ""
                old_storage = profile.signature_image.storage if profile.signature_image else None
                old_stamp = profile.stamp_image.name if profile.stamp_image else ""
                old_stamp_storage = profile.stamp_image.storage if profile.stamp_image else None
                remove_signature = signature_form.cleaned_data["clear_signature"]
                remove_stamp = signature_form.cleaned_data["clear_stamp"]
                new_upload = bool(request.FILES.get("signature_image"))
                new_stamp_upload = bool(request.FILES.get("stamp_image"))
                profile = signature_form.save(commit=False)
                profile.signature_document_types = signature_form.cleaned_data["signature_document_types"]
                profile.stamp_document_types = signature_form.cleaned_data["stamp_document_types"]
                if remove_signature and not new_upload:
                    profile.signature_image = ""
                if remove_stamp and not new_stamp_upload:
                    profile.stamp_image = ""
                profile.save()
                signature_form.save_m2m()
                if old_signature and old_signature != profile.signature_image.name and old_storage:
                    from apps.bids.retention import delete_stored_file_if_unreferenced
                    delete_stored_file_if_unreferenced(old_storage, old_signature)
                if old_stamp and old_stamp != profile.stamp_image.name and old_stamp_storage:
                    from apps.bids.retention import delete_stored_file_if_unreferenced
                    delete_stored_file_if_unreferenced(old_stamp_storage, old_stamp)

                from apps.generation.models import BidPreparation, GeneratedDocument
                from apps.generation.views import _store_generated_pdf
                docs = GeneratedDocument.objects.filter(bid__uploaded_by=request.user).select_related("bid")
                refreshed = 0
                for generated in docs:
                    preparation = BidPreparation.objects.filter(bid=generated.bid).first()
                    if not preparation:
                        continue
                    _store_generated_pdf(generated, profile, preparation, generated.document_type, generated.title, generated.editable_content or None)
                    refreshed += 1
                if refreshed:
                    messages.success(request, f"Signature and stamp settings saved. Refreshed {refreshed} generated PDF(s).")
                else:
                    messages.success(request, "Signature and stamp settings saved to the company profile.")
                return redirect("company-profile")
        elif form_action in {"document_signature", "document_marks"}:
            document = get_object_or_404(CompanyDocument, pk=request.POST.get("document_id"), company__owner=request.user)
            document.include_signature = request.POST.get("include_signature") == "on"
            document.include_stamp = request.POST.get("include_stamp") == "on"
            document.save(update_fields=["include_signature", "include_stamp"])
            messages.success(request, f"Signature and stamp settings saved for {document.title}.")
            return redirect("company-profile")
        elif form_action == "document":
            if not profile:
                profile = CompanyProfile.objects.create(owner=request.user)
            document_form = CompanyDocumentForm(request.POST, request.FILES)
            profile_form = CompanyProfileForm(instance=profile)
            signature_form = CompanySignatureForm(instance=profile)
            if document_form.is_valid():
                doc = document_form.save(commit=False)
                doc.company = profile
                doc.save()
                messages.success(request, "Supporting document saved.")
                return redirect("company-profile")
        else:
            profile_form = CompanyProfileForm(request.POST, instance=profile)
            document_form = CompanyDocumentForm()
            signature_form = CompanySignatureForm(instance=profile)
            if profile_form.is_valid():
                profile = profile_form.save(commit=False)
                profile.owner = request.user
                profile.save()
                messages.success(request, "Company profile saved.")
                return redirect("company-profile")
    else:
        profile_form = CompanyProfileForm(instance=profile)
        document_form = CompanyDocumentForm()
        signature_form = CompanySignatureForm(instance=profile)
    documents = profile.documents.order_by("-created_at") if profile else []
    return render(request, "companies/profile.html", {"profile": profile, "profile_form": profile_form, "document_form": document_form, "signature_form": signature_form, "documents": documents})


@login_required
def view_company_document(request, document_id):
    document = get_object_or_404(CompanyDocument, pk=document_id, company__owner=request.user)
    profile = document.company
    if request.GET.get("self_attest") == "1":
        from .self_attestation import self_attested_pdf
        try:
            data = self_attested_pdf(document, profile)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise Http404("Could not prepare a self-attested copy of this document.") from exc
        response = HttpResponse(data, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{Path(document.file.name).stem}-signed.pdf"'
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        return response
    try:
        document.file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("Supporting document not found.")
    is_pdf = document.file.name.lower().endswith(".pdf")
    response = FileResponse(document.file, content_type="application/pdf" if is_pdf else "application/octet-stream", as_attachment=not is_pdf, filename=document.file.name.rsplit("/", 1)[-1])
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
def view_company_signature(request):
    profile = get_object_or_404(CompanyProfile, owner=request.user)
    if not profile.signature_image:
        raise Http404("No saved signature image.")
    try:
        from .signatures import styled_signature
        if request.GET.get("editor") == "1":
            profile.signature_rotation = 0
        signature_data = styled_signature(profile)
    except (FileNotFoundError, OSError):
        raise Http404("Saved signature image not found.")
    response = HttpResponse(signature_data, content_type="image/png")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
def view_company_stamp(request):
    profile = get_object_or_404(CompanyProfile, owner=request.user)
    if not profile.stamp_image:
        raise Http404("No saved company stamp.")
    try:
        from .signatures import stamp_image_bytes
        if request.GET.get("editor") == "1":
            profile.stamp_rotation = 0
        stamp_data = stamp_image_bytes(profile)
    except (FileNotFoundError, OSError):
        raise Http404("Saved company stamp not found.")
    response = HttpResponse(stamp_data, content_type="image/png")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response
