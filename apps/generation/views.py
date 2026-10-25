import copy
import re
from decimal import Decimal, InvalidOperation
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from apps.bids.models import Bid
from apps.companies.models import CompanyProfile
from services.requirements import build_requirements_metadata
from .forms import BidBOQFormSet, BidPreparationForm, CustomDocumentForm
from .models import BidPreparation, CustomDocumentTemplate, GeneratedDocument
from .boq_extraction import extracted_boq_tables, import_cached_linked_boq_tables
from .extraction import suggested_preparation_values, sync_missing_preparation_fields
from .services.pdf_documents import (
    DOCUMENTS,
    EDITABLE_TEMPLATE_VERSION,
    add_current_signatory_date,
    build_document,
    editable_document_text,
    _letterhead_for_legacy_content,
    ensure_source_boq_tables,
    normalize_generated_document_text,
    _with_standard_footer,
    remove_source_pdf_filename_lines,
)

MAX_EDITABLE_CONTENT_LENGTH = 100000


DOCUMENT_POSITION_FIELDS = (
    "signature_position_x",
    "signature_position_y",
    "stamp_position_x",
    "stamp_position_y",
)


def _profile_is_complete(profile):
    return bool(profile and profile.legal_name.strip() and profile.address.strip() and profile.signatory_name.strip())


def _document_positions(profile, document, data=None):
    positions = {}
    for field in DOCUMENT_POSITION_FIELDS:
        saved_position = getattr(document, field)
        fallback = saved_position if saved_position is not None else getattr(profile, field)
        value = data.get(field) if data is not None else None
        if value in (None, ""):
            positions[field] = Decimal(str(fallback))
            continue
        try:
            position = Decimal(value)
        except (InvalidOperation, TypeError):
            raise ValueError(f"{field.replace('_', ' ').capitalize()} must be a number between 0 and 100.")
        if not position.is_finite() or position < 0 or position > 100:
            raise ValueError(f"{field.replace('_', ' ').capitalize()} must be between 0 and 100.")
        positions[field] = position
    return positions


def _profile_with_positions(profile, positions):
    positioned_profile = copy.copy(profile)
    for field, value in positions.items():
        setattr(positioned_profile, field, value)
    return positioned_profile


def _document_mark_setting(document, submitted=None):
    if submitted is not None:
        return submitted
    settings = document.render_settings or {}
    if "include_signature_stamp" in settings:
        return bool(settings["include_signature_stamp"])
    return document.document_type.startswith("custom_")


def _profile_with_document_marks(profile, document, include_marks):
    """Apply this document's mark choice without changing the company profile."""
    positioned_profile = copy.copy(profile)
    if document.document_type.startswith("custom_"):
        for field in ("signature_document_types", "stamp_document_types"):
            enabled_types = list(getattr(profile, field) or [])
            if include_marks and document.document_type not in enabled_types:
                enabled_types.append(document.document_type)
            elif not include_marks:
                enabled_types = [item for item in enabled_types if item != document.document_type]
            setattr(positioned_profile, field, enabled_types)
    return positioned_profile


def _suggested_prep(bid):
    return BidPreparation(bid=bid, **suggested_preparation_values(bid))


def _render_custom_template(template, profile, prep, document_type):
    """Fill supported per-bid tokens before applying the standard PDF header."""
    from .services.pdf_documents import _recipient_line

    bid_number = prep.bid_number or prep.bid.bid_number or "Bid number not recorded"
    values = {
        "to": _recipient_line(prep).removeprefix("To: ").strip(),
        "bid_number": bid_number,
        "bid_title": prep.bid_title or prep.bid.title or "",
        "buyer_name": prep.buyer_name or "",
        "buyer_department": prep.buyer_department or "",
        "company_name": profile.legal_name or profile.trade_name or "",
        "signatory_name": profile.signatory_name or "",
        "date": timezone.localdate().strftime("%d %B %Y"),
    }
    content = template.content
    for key, value in values.items():
        content = content.replace("{{" + key + "}}", value).replace("{{ " + key + " }}", value)
    content = re.sub(r"(?im)^\s*To\s*:.*$", _recipient_line(prep), content, count=1)
    return editable_document_text(profile, prep, document_type, template.title, body=content)


def _store_generated_pdf(row, profile, prep, document_type, title, content):
    if content is None:
        content = row.editable_content or editable_document_text(profile, prep, document_type, title)
    elif row.template_version != EDITABLE_TEMPLATE_VERSION:
        if row.template_version == "1.4":
            content = add_current_signatory_date(content)
            content = _letterhead_for_legacy_content(profile, prep, title, content)
        elif row.template_version in {"1.5", "1.6", "1.7", "1.8", "1.9", "2.0", "2.1", "2.2", "2.3", "2.4"}:
            content = _letterhead_for_legacy_content(profile, prep, title, content)
        else:
            # Older records stored only the declaration body. Upgrade them
            # while retaining their text and adding the document sections.
            content = editable_document_text(profile, prep, document_type, title, body=content)
    content = normalize_generated_document_text(content)
    content = ensure_source_boq_tables(content, prep, document_type)
    content = _with_standard_footer(profile, prep, content)
    content = remove_source_pdf_filename_lines(content)
    _title = dict(DOCUMENTS).get(document_type, title)
    previous_name = row.file.name if row.file else ""
    previous_storage = row.file.storage if previous_name else None
    row.title = title or _title
    row.editable_content = content
    row.template_version = EDITABLE_TEMPLATE_VERSION
    row.file = ""
    row.save()
    if previous_name and previous_storage:
        from apps.bids.retention import delete_stored_file_if_unreferenced
        delete_stored_file_if_unreferenced(previous_storage, previous_name)
    return row


@login_required
def prepare_bid(request, bid_id):
    bid = Bid.objects.filter(pk=bid_id, uploaded_by=request.user).first()
    if bid is None:
        messages.warning(
            request,
            "That bid is no longer available. It may have been completed, deleted, or expired. Check your active bids.",
        )
        return redirect("bid-dashboard")
    profile = CompanyProfile.objects.filter(owner=request.user).first()
    if bid.status == Bid.Status.READY and bid.extracted_text:
        metadata = bid.extracted_metadata or {}
        requirements_analysis = build_requirements_metadata(bid.extracted_text, profile)
        if metadata.get("requirements_analysis") != requirements_analysis:
            metadata["requirements_analysis"] = requirements_analysis
            bid.extracted_metadata = metadata
            bid.save(update_fields=["extracted_metadata", "updated_at"])

    suggestions = _suggested_prep(bid)
    prep, created = BidPreparation.objects.get_or_create(bid=bid, defaults={
        "bid_number": bid.bid_number or suggestions.bid_number,
        "bid_title": suggestions.bid_title or bid.title,
        "buyer_name": suggestions.buyer_name,
        "buyer_department": suggestions.buyer_department,
        "buyer_address": suggestions.buyer_address,
        "beneficiary_details": suggestions.beneficiary_details,
        "bid_date": suggestions.bid_date,
        "required_experience_years": suggestions.required_experience_years,
        "bidder_turnover_threshold": suggestions.bidder_turnover_threshold,
        "oem_turnover_threshold": suggestions.oem_turnover_threshold,
        "payment_note": suggestions.payment_note,
        "invoice_gstin": suggestions.invoice_gstin or (profile.gstin if profile else ""),
        "invoice_address": suggestions.invoice_address or (profile.address if profile else ""),
    })
    # Extraction runs asynchronously. If the preparation page was opened
    # before it completed, fill newly extracted values on the next visit.
    sync_missing_preparation_fields(bid)
    prep.refresh_from_db()
    # Clear an earlier broad-text match that can point at a tender question instead of the organisation label.
    if prep.buyer_name and ("seeking experience" in prep.buyer_name.lower() or prep.buyer_name[:1].isdigit()):
        prep.buyer_name = suggestions.buyer_name
        prep.save(update_fields=["buyer_name", "updated_at"])
    if not prep.invoice_gstin and profile and profile.gstin:
        prep.invoice_gstin = profile.gstin
    if not prep.invoice_address and profile and profile.address:
        prep.invoice_address = profile.address
    if not extracted_boq_tables(prep):
        import_cached_linked_boq_tables(prep)

    if request.method == "POST":
        prep_form = BidPreparationForm(request.POST, instance=prep)
        item_formset = BidBOQFormSet(request.POST, instance=prep, prefix="boq")
        custom_document_form = CustomDocumentForm(request.POST)
        action = request.POST.get("action", "save")
        custom_document_valid = action != "create_custom" or custom_document_form.is_valid()
        if prep_form.is_valid() and item_formset.is_valid() and custom_document_valid:
            prep = prep_form.save(commit=False)
            prep.bid = bid
            prep.save()
            item_formset.instance = prep
            item_formset.save()
            if action.startswith("generate:"):
                document_type = action.split(":", 1)[1]
                if not _profile_is_complete(profile):
                    messages.error(request, "Complete the company legal name, address, and authorized signatory in Company Profile before generating PDFs.")
                    return redirect("company-profile")
                if document_type not in dict(DOCUMENTS):
                    return HttpResponseBadRequest("Unsupported document type.")
                row, created = GeneratedDocument.objects.get_or_create(
                    bid=bid,
                    document_type=document_type,
                    defaults={"title": dict(DOCUMENTS)[document_type], "generated_by": request.user},
                )
                # Regeneration must use the saved editable draft. Only build
                # from the current default when this PDF has no saved text.
                saved_content = None if created else (row.editable_content or None)
                _store_generated_pdf(
                    row,
                    profile,
                    prep,
                    document_type,
                    dict(DOCUMENTS)[document_type],
                    saved_content,
                )
                messages.success(request, f"{row.title} is ready to edit or download.")
                return redirect("generated-document-edit", document_id=row.pk)
            if action.startswith("template:"):
                template_id = action.split(":", 1)[1]
                template = get_object_or_404(CustomDocumentTemplate, pk=template_id, owner=request.user)
                if not _profile_is_complete(profile):
                    messages.error(request, "Complete the company legal name, address, and authorized signatory in Company Profile before generating PDFs.")
                    return redirect("company-profile")
                document_type = f"custom_template_{template.pk}"
                row, created = GeneratedDocument.objects.get_or_create(
                    bid=bid,
                    document_type=document_type,
                    defaults={
                        "title": template.title,
                        "generated_by": request.user,
                        "template_version": EDITABLE_TEMPLATE_VERSION,
                    },
                )
                saved_content = None if created else (row.editable_content or None)
                if saved_content is None:
                    # Reuse the same letterhead and recipient handling as built-in PDFs.
                    saved_content = _render_custom_template(template, profile, prep, document_type)
                _store_generated_pdf(row, profile, prep, document_type, template.title, saved_content)
                messages.success(request, f"{row.title} is ready to edit or download.")
                return redirect("generated-document-edit", document_id=row.pk)
            if action == "create_custom":
                if not _profile_is_complete(profile):
                    messages.error(request, "Complete the company legal name, address, and authorized signatory in Company Profile before generating PDFs.")
                    return redirect("company-profile")
                title = custom_document_form.cleaned_data["title"].strip()
                content = custom_document_form.cleaned_data["content"].strip()
                if not title or not content:
                    custom_document_form.add_error(None, "Enter both a title and document text.")
                else:
                    template = CustomDocumentTemplate.objects.create(owner=request.user, title=title, content=content)
                    document_type = f"custom_template_{template.pk}"
                    row = GeneratedDocument.objects.create(
                        bid=bid,
                        document_type=document_type,
                        title=title,
                        generated_by=request.user,
                        template_version=EDITABLE_TEMPLATE_VERSION,
                    )
                    content = _render_custom_template(template, profile, prep, document_type)
                    _store_generated_pdf(row, profile, prep, document_type, title, content)
                    messages.success(request, f"{row.title} is ready to edit or download.")
                    return redirect("generated-document-edit", document_id=row.pk)
            messages.success(request, "Bid details saved. Generate and edit each required PDF below.")
            return redirect("bid-prepare", bid_id=bid.pk)
    else:
        prep_form = BidPreparationForm(instance=prep)
        item_formset = BidBOQFormSet(instance=prep, prefix="boq")
        custom_document_form = CustomDocumentForm()
    generated = GeneratedDocument.objects.filter(bid=bid, generated_by=request.user)
    generated_by_type = {doc.document_type: doc for doc in generated}
    requirements_analysis = (bid.extracted_metadata or {}).get("requirements_analysis", {})
    required_types = {
        item.get("document_type")
        for item in requirements_analysis.get("required_documents", [])
        if item.get("is_required", True)
    }
    document_rows = [(key, label, generated_by_type.get(key), f"generate:{key}") for key, label in DOCUMENTS]
    document_rows.extend(
        (document.document_type, document.title, document, f"generate:{document.document_type}")
        for document in generated
        if document.document_type.startswith("custom_")
    )
    custom_templates = CustomDocumentTemplate.objects.filter(owner=request.user)
    for template in custom_templates:
        document_type = f"custom_template_{template.pk}"
        if document_type not in generated_by_type:
            document_rows.append((document_type, template.title, None, f"template:{template.pk}"))
        else:
            document_rows = [
                (doc_type, label, document, f"template:{template.pk}" if doc_type == document_type else action_value)
                for doc_type, label, document, action_value in document_rows
            ]
    return render(request, "generation/prepare.html", {
        "bid": bid,
        "profile": profile,
        "prep": prep,
        "prep_form": prep_form,
        "item_formset": item_formset,
        "extracted_boq_tables": extracted_boq_tables(prep),
        "document_rows": document_rows,
        "requirements_analysis": requirements_analysis,
        "requirements_were_detected": bool(required_types),
        "custom_document_form": custom_document_form,
    })


@login_required
def edit_generated_document(request, document_id):
    document = get_object_or_404(GeneratedDocument, pk=document_id, generated_by=request.user, bid__uploaded_by=request.user)
    profile = CompanyProfile.objects.filter(owner=request.user).first()
    if not _profile_is_complete(profile):
        messages.error(request, "Complete the company legal name, address, and authorized signatory in Company Profile before generating PDFs.")
        return redirect("company-profile")
    if request.method == "POST":
        content = request.POST.get("editable_content", "")
        if len(content) > MAX_EDITABLE_CONTENT_LENGTH:
            return HttpResponseBadRequest(f"Document text must be {MAX_EDITABLE_CONTENT_LENGTH:,} characters or less.")
        profile = profile or get_object_or_404(CompanyProfile, owner=request.user)
        try:
            positions = _document_positions(profile, document, request.POST)
        except ValueError as exc:
            return HttpResponseBadRequest(str(exc))
        for field, value in positions.items():
            setattr(document, field, value)
        if document.document_type.startswith("custom_"):
            render_settings = dict(document.render_settings or {})
            render_settings["include_signature_stamp"] = request.POST.get("add_signature_stamp") == "on"
            document.render_settings = render_settings
        _store_generated_pdf(document, profile, document.bid.preparation, document.document_type, document.title, content)
        if request.POST.get("download_after_save") == "1":
            return redirect(f"{reverse('generated-document-view', args=[document.pk])}?download=1")
        if request.POST.get("open_after_save") == "1":
            return redirect("generated-document-view", document_id=document.pk)
        messages.success(request, "Your edits are saved and the PDF has been regenerated.")
        return redirect("generated-document-edit", document_id=document.pk)
    if document.template_version != EDITABLE_TEMPLATE_VERSION:
        profile = profile or get_object_or_404(CompanyProfile, owner=request.user)
        _store_generated_pdf(document, profile, document.bid.preparation, document.document_type, document.title, document.editable_content or None)
    include_signature_stamp = _document_mark_setting(document)
    signature_enabled = bool(
        profile
        and (include_signature_stamp or not document.document_type.startswith("custom_"))
        and (
            document.document_type.startswith("custom_")
            or document.document_type in (profile.signature_document_types or [])
        )
    )
    stamp_enabled = bool(
        profile
        and (include_signature_stamp or not document.document_type.startswith("custom_"))
        and (
            document.document_type.startswith("custom_")
            or document.document_type in (profile.stamp_document_types or [])
        )
    )
    positions = _document_positions(profile, document) if profile else {}
    return render(request, "generation/edit_document.html", {
        "document": document,
        "max_editable_content_length": MAX_EDITABLE_CONTENT_LENGTH,
        "signature_enabled": signature_enabled,
        "stamp_enabled": stamp_enabled,
        "include_signature_stamp": include_signature_stamp,
        "is_custom_document": document.document_type.startswith("custom_"),
        "profile_updated_at": int(profile.updated_at.timestamp() * 1_000_000) if profile else 0,
        "mark_positions": positions,
    })


@login_required
@require_POST
@xframe_options_sameorigin
def preview_generated_document(request, document_id):
    document = get_object_or_404(GeneratedDocument, pk=document_id, generated_by=request.user, bid__uploaded_by=request.user)
    content = request.POST.get("editable_content", "")
    if len(content) > MAX_EDITABLE_CONTENT_LENGTH:
        return HttpResponseBadRequest(f"Document text must be {MAX_EDITABLE_CONTENT_LENGTH:,} characters or less.")
    profile = CompanyProfile.objects.filter(owner=request.user).first()
    if not _profile_is_complete(profile):
        return HttpResponseBadRequest("Complete the company legal name, address, and authorized signatory in Company Profile before generating PDFs.")
    try:
        positions = _document_positions(profile, document, request.POST)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    include_marks = _document_mark_setting(
        document,
        request.POST.get("add_signature_stamp") == "on" if document.document_type.startswith("custom_") else None,
    )
    _title, _content, pdf = build_document(
        _profile_with_document_marks(_profile_with_positions(profile, positions), document, include_marks),
        document.bid.preparation,
        document.document_type,
        content,
        document.title,
    )
    response = HttpResponse(pdf, content_type="application/pdf")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_POST
def delete_custom_generated_document(request, document_id):
    document = get_object_or_404(
        GeneratedDocument.objects.select_related("bid"),
        pk=document_id,
        generated_by=request.user,
        bid__uploaded_by=request.user,
        document_type__startswith="custom_",
    )
    file_name = document.file.name if document.file else ""
    file_storage = document.file.storage if file_name else None
    bid_id = document.bid_id
    document.delete()
    if file_name and file_storage:
        from apps.bids.retention import delete_stored_file_if_unreferenced
        delete_stored_file_if_unreferenced(file_storage, file_name)
    messages.success(request, "Custom PDF deleted.")
    return redirect("bid-prepare", bid_id=bid_id)


@login_required
@xframe_options_sameorigin
def view_generated_document(request, document_id):
    doc = get_object_or_404(GeneratedDocument, pk=document_id, generated_by=request.user, bid__uploaded_by=request.user)
    profile = CompanyProfile.objects.filter(owner=request.user).first()
    if not _profile_is_complete(profile):
        messages.error(request, "Complete the company legal name, address, and authorized signatory in Company Profile before generating PDFs.")
        return redirect("company-profile")
    if doc.template_version != EDITABLE_TEMPLATE_VERSION:
        _store_generated_pdf(
            doc,
            profile,
            doc.bid.preparation,
            doc.document_type,
            doc.title,
            doc.editable_content or None,
        )
    if doc.file:
        try:
            doc.file.open("rb")
            response = FileResponse(doc.file, content_type="application/pdf")
        except OSError as exc:
            raise Http404("Generated PDF not found.") from exc
        download = request.GET.get("download") == "1"
        response["Content-Disposition"] = f'{"attachment" if download else "inline"}; filename="{slugify(doc.title)[:70] or "bid-document"}.pdf"'
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        return response
    positions = _document_positions(profile, doc)
    include_marks = _document_mark_setting(doc)
    _title, _content, pdf = build_document(
        _profile_with_document_marks(_profile_with_positions(profile, positions), doc, include_marks),
        doc.bid.preparation,
        doc.document_type,
        doc.editable_content or None,
        doc.title,
    )
    response = HttpResponse(pdf, content_type="application/pdf")
    download = request.GET.get("download") == "1"
    response["Content-Disposition"] = f'{"attachment" if download else "inline"}; filename="{slugify(doc.title)[:70] or "bid-document"}.pdf"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response
