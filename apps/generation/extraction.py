import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date

from .models import BidPreparation


PREPARATION_FIELDS = (
    "bid_number",
    "bid_title",
    "buyer_name",
    "buyer_department",
    "buyer_address",
    "bid_date",
    "required_experience_years",
    "bidder_turnover_threshold",
    "oem_turnover_threshold",
    "invoice_gstin",
    "invoice_address",
    "payment_note",
)


def _label_value(lines, pattern):
    for index, line in enumerate(lines):
        # GeM PDFs frequently prefix English labels with Hindi text/control
        # glyphs, so look for the label within the line instead of anchoring
        # it at the beginning.
        match = re.search(rf"(?:{pattern})\s*(?::|[-–])?\s*(.*)$", line, re.I)
        if not match:
            continue
        value = re.sub(r"\s+", " ", match.group(1)).strip(" :-–\t")
        if value:
            return value
        if index + 1 < len(lines):
            value = re.sub(r"\s+", " ", lines[index + 1]).strip()
            if value and not re.match(r"^[A-Za-z][A-Za-z /()-]{1,40}\s*:", value):
                return value
    return ""


def _as_date(value):
    if not value:
        return None
    value = str(value).strip()
    result = parse_date(value[:10])
    if result:
        return result
    for date_format in ("%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue
    return None


def _as_decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _as_integer(value):
    if value in (None, ""):
        return None
    try:
        return int(Decimal(str(value).replace(",", "").strip()))
    except (InvalidOperation, ValueError, TypeError):
        return None


def suggested_preparation_values(bid):
    """Build normalized bid/buyer defaults from PDF text and local analysis."""
    text = bid.extracted_text or ""
    analysis = (bid.extracted_metadata or {}).get("requirements_analysis", {}).get("bid_analysis", {})
    lines = [
        re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f]+", "", line)).strip()
        for line in text.splitlines()
        if line.strip()
    ]

    bid_number = bid.bid_number or analysis.get("bid_number") or ""
    if not bid_number:
        match = re.search(r"GEM\s*/\s*\d{4}\s*/\s*B\s*/\s*\d+", text, re.I)
        bid_number = re.sub(r"\s+", "", match.group(0)).upper() if match else ""

    bid_title = analysis.get("item_name") or analysis.get("title") or bid.title or ""
    if not bid_title:
        bid_title = _label_value(lines, r"(?:BOQ\s+Title|Item\s+Category|Bid\s+Title)")
    buyer_name = analysis.get("buyer_name") or analysis.get("organization") or ""
    if not buyer_name:
        buyer_name = _label_value(lines, r"(?:Buyer\s+)?(?:Organisation|Organization|Office)\s+Name")
    buyer_department = analysis.get("buyer_department") or analysis.get("department") or ""
    if not buyer_department:
        buyer_department = _label_value(lines, r"(?:Buyer\s+)?Department\s+Name")
    buyer_address = analysis.get("buyer_address") or _label_value(lines, r"Buyer\s+Address")

    experience = re.search(r"Years of Past Experience Required.*?\n\s*(\d+)\s*Year", text, re.I | re.S)
    bidder_turnover = re.search(
        r"Minimum Average Annual Turnover of the\s*bidder.*?\n\s*([\d,.]+)\s*Lakh", text, re.I | re.S
    )
    oem_turnover = re.search(r"OEM Average Turnover.*?\n\s*([\d,.]+)\s*Lakh", text, re.I | re.S)
    exp_value = experience.group(1) if experience else analysis.get("required_experience_years")
    bidder_value = float(bidder_turnover.group(1).replace(",", "")) * 100000 if bidder_turnover else analysis.get("bidder_turnover_threshold")
    oem_value = float(oem_turnover.group(1).replace(",", "")) * 100000 if oem_turnover else analysis.get("oem_turnover_threshold")

    return {
        "bid_number": str(bid_number)[:120] if bid_number else "",
        "bid_title": str(bid_title)[:255] if bid_title else "",
        "buyer_name": str(buyer_name)[:255] if buyer_name else "",
        "buyer_department": str(buyer_department)[:255] if buyer_department else "",
        "buyer_address": str(buyer_address)[:4000] if buyer_address else "",
        "bid_date": _as_date(analysis.get("bid_date")),
        "required_experience_years": _as_integer(exp_value),
        "bidder_turnover_threshold": _as_decimal(bidder_value),
        "oem_turnover_threshold": _as_decimal(oem_value),
        "invoice_gstin": str(analysis.get("invoice_gstin") or "")[:15],
        "invoice_address": str(analysis.get("invoice_address") or ""),
        "payment_note": str(analysis.get("payment_terms") or ""),
    }


def sync_missing_preparation_fields(bid):
    """Backfill blank preparation values without overwriting user-entered data."""
    try:
        prep = BidPreparation.objects.filter(bid_id=bid.pk).first()
    except (BidPreparation.DoesNotExist, ValueError):
        return
    if not prep:
        return
    suggested = suggested_preparation_values(bid)
    updates = {}
    empty_fields = Q()
    for field in PREPARATION_FIELDS:
        value = suggested.get(field)
        if value in (None, ""):
            continue
        current = getattr(prep, field)
        if current not in (None, ""):
            continue
        empty_fields &= Q(**{f"{field}__isnull": True}) if current is None else Q(**{field: ""})
        updates[field] = value
    if updates:
        BidPreparation.objects.filter(pk=prep.pk).filter(empty_fields).update(**updates, updated_at=timezone.now())
