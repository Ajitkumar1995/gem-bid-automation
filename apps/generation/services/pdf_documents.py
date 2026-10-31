"""
Template-based PDF document generation for GeM bids.
Python renders built-in and user-authored document text as PDFs.
"""
from html import escape
from io import BytesIO
import re
from typing import List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.lib.units import mm
from reportlab.platypus import Flowable
from reportlab.platypus import (
    HRFlowable, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
)
from django.utils import timezone
from apps.companies.signatures import stamp_image_bytes, styled_signature
from apps.generation.boq_extraction import editable_source_values, source_field_for_header


# Document type definitions - ALL documents that can be generated
DOCUMENTS = [
    ("experience_declaration", "Experience Declaration"),
    ("past_performance", "Past Performance / MSME Relaxation"),
    ("bidder_turnover", "Bidder Turnover Declaration"),
    ("msme_turnover_exemption", "MSME Turnover Exemption Declaration"),
    ("undertaking", "Undertaking"),
    ("declaration", "Declaration"),
    ("authorization_letter", "Authorization Letter"),
    ("technical_compliance", "Technical Compliance Statement"),
    ("non_blacklisting_declaration", "Non-Blacklisting Declaration"),
    ("turnover_declaration", "Turnover Declaration"),
    ("mse_startup_declaration", "MSE / Startup Declaration"),
    ("additional_doc_1", "Additional Document 1 – BoQ Compliance"),
    ("additional_doc_2", "Additional Document 2 (Supporting Documents Index)"),
    ("atc_certificate", "ATC Supporting Documents"),
    ("boq_specifications", "Compliance to BoQ Specifications"),
    ("oem_annual_turnover", "OEM Annual Turnover Evidence"),
]

DOCUMENTS_DICT = dict(DOCUMENTS)
EDITABLE_TEMPLATE_VERSION = "2.5"


def add_current_signatory_date(content: str) -> str:
    """Add a generated date below the signature image and before the place."""
    lines = content.splitlines()
    if any(line.strip().startswith("Date:") for line in lines):
        return content
    signature_index = next(
        (index for index, line in enumerate(lines) if line.strip() == "Signature:"),
        None,
    )
    place_index = next(
        (index for index, line in enumerate(lines) if line.strip().startswith("Place:")),
        None,
    )
    if signature_index is None or place_index is None or signature_index >= place_index:
        return content
    lines.insert(place_index, f"Date: {timezone.localdate().strftime('%d %B %Y')}")
    return "\n".join(lines)


class SignatureStampBlock(Flowable):
    """Draw the stamp and signature at saved positions with separate labels."""

    def __init__(
        self,
        stamp_data: bytes,
        signature_data: bytes,
        signature_scale: float,
        stamp_scale: float,
        signature_position_x: float = 0,
        signature_position_y: float = 50,
        stamp_position_x: float = 77,
        stamp_position_y: float = 50,
    ):
        super().__init__()
        self.hAlign = "LEFT"
        self.stamp_reader = ImageReader(BytesIO(stamp_data)) if stamp_data else None
        self.signature_reader = ImageReader(BytesIO(signature_data)) if signature_data else None
        self.stamp_size = self._image_size(self.stamp_reader, 26 * mm, 20 * mm, stamp_scale)
        self.signature_size = self._image_size(self.signature_reader, 38 * mm, 30 * mm, signature_scale)
        self.width = 170 * mm - 12
        self.height = 30 * mm * max(signature_scale, stamp_scale, 1 if stamp_data or signature_data else 0)
        self.signature_position = (signature_position_x / 100, signature_position_y / 100)
        self.stamp_position = (stamp_position_x / 100, stamp_position_y / 100)

    @staticmethod
    def _image_size(reader, max_width, max_height, scale):
        if reader is None:
            return 0, 0
        image_width, image_height = reader.getSize()
        factor = min(max_width / image_width, max_height / image_height, 1) * scale
        return image_width * factor, image_height * factor

    def wrap(self, available_width, available_height):
        return self.width, self.height

    def draw(self):
        if self.signature_reader:
            signature_width, signature_height = self.signature_size
            signature_x = self._center(self.signature_position[0] * self.width, signature_width, self.width)
            signature_y = self._center((1 - self.signature_position[1]) * self.height, signature_height, self.height)
            self.canv.drawImage(
                self.signature_reader,
                signature_x,
                signature_y,
                width=signature_width,
                height=signature_height,
                mask="auto",
            )
        else:
            self.canv.setLineWidth(0.7)
            self.canv.line(0, self.height * 0.42, 38 * mm, self.height * 0.42)
        if self.stamp_reader:
            stamp_width, stamp_height = self.stamp_size
            stamp_x = self._center(self.stamp_position[0] * self.width, stamp_width, self.width)
            stamp_y = self._center((1 - self.stamp_position[1]) * self.height, stamp_height, self.height)
            self.canv.drawImage(
                self.stamp_reader,
                stamp_x,
                stamp_y,
                width=stamp_width,
                height=stamp_height,
                mask="auto",
            )

    @staticmethod
    def _center(position, mark_size, area_size):
        if mark_size >= area_size:
            return 0
        return min(max(0, position - mark_size / 2), area_size - mark_size)


def _e(value: str) -> str:
    """Escape HTML for PDF content."""
    return escape(str(value or ""))


def _place(profile) -> str:
    """Return the signatory place from the reusable company profile."""
    city_state = ", ".join(value.strip() for value in (profile.city, profile.state) if value and value.strip())
    return city_state or profile.address.strip() or "____________________"


def _letterhead(profile, prep, title: str) -> str:
    """Build the standard company letterhead."""
    company_name = (profile.legal_name or profile.trade_name or "Bidder").strip()
    if not re.match(r"m\s*/\s*s\b", company_name, re.IGNORECASE):
        company_name = f"M/S {company_name}"
    lines = [company_name.upper()]

    address_parts = [
        part.strip()
        for part in profile.address.replace("\n", ",").split(",")
        if part.strip()
    ]
    city_state_parts = {
        part.strip().casefold()
        for part in (profile.city, profile.state)
        if part and part.strip()
    }
    locality_candidates = []
    for part in address_parts:
        if (
            part.casefold() in city_state_parts
            or re.search(r"\b(?:WARD|NEAR|OPPOSITE|OPP|LANDMARK|STUDIO)\b", part, re.IGNORECASE)
        ):
            continue
        locality = re.sub(
            r"\s+(?:(?:MAIN|LINK|BYPASS)\s+)?(?:ROAD|RD|STREET|ST|LANE|LN|HIGHWAY|HWY)\.?$",
            "",
            part,
            flags=re.IGNORECASE,
        ).strip(" ,.-")
        if locality and re.search(r"[A-Z]", locality, re.IGNORECASE):
            locality_candidates.append(locality)
    address_parts = locality_candidates[-1:]
    existing_parts = {part.casefold() for part in address_parts}
    for part in (profile.city, profile.state):
        if part and part.strip() and part.strip().casefold() not in existing_parts:
            address_parts.append(part.strip())
            existing_parts.add(part.strip().casefold())
    address = ", ".join(address_parts)
    pincode = (profile.pincode or "").strip()
    if pincode and pincode.casefold() not in address.casefold():
        address = f"{address}, {pincode}" if address else pincode
    if address:
        lines.append(address.upper())
    if profile.gstin:
        lines.append(f"GSTIN: {profile.gstin.upper()}")
    return "\n\n".join((
        "\n".join(lines),
        title.upper(),
    ))


def _letterhead_for_legacy_content(profile, prep, title: str, content: str) -> str:
    """Replace generated header variants while retaining the document body."""
    sections = content.split("\n\n")
    letterhead_index = next(
        (
            index
            for index, section in enumerate(sections)
            if section.lstrip().startswith("M/S ")
        ),
        None,
    )
    if letterhead_index is not None:
        body_index = letterhead_index + 2
        if len(sections) > body_index and sections[body_index].startswith(("GeM Bid No.:", "Date:")):
            body_index += 1
        content = "\n\n".join(sections[body_index:])
    elif (
        len(sections) >= 4
        and sections[1].startswith("Bid:")
        and sections[2].startswith("Buyer:")
        and sections[3].startswith("Bidder:")
    ):
        content = "\n\n".join(sections[4:])
    header = _letterhead(profile, prep, title)
    return f"{header}\n\n{content}" if content else header


def normalize_generated_document_text(content: str) -> str:
    """Remove superseded header metadata and standardize the company locality."""
    lines = content.splitlines()
    recipient_index = next(
        (index for index, line in enumerate(lines) if re.match(r"^\s*To\s*:", line, re.IGNORECASE)),
        None,
    )
    if recipient_index is not None:
        lines = [
            line
            for index, line in enumerate(lines)
            if index >= recipient_index
            or not re.match(r"^\s*(?:GeM Bid No\.:|Date:)", line, re.IGNORECASE)
        ]
    return re.sub(r"\bMOKAMEH\b", "AUNTA", "\n".join(lines), flags=re.IGNORECASE)


def remove_company_letterhead_footer(content: str) -> str:
    """Remove an existing standard or partial signatory footer, if present."""
    marker = "\n\nDeclaration\n"
    marker_position = content.rfind(marker)
    while marker_position >= 0:
        old_footer = content[marker_position:]
        if all(
            required in old_footer
            for required in ("Authorized Signatory", "Company Seal and Stamp", "Place:")
        ):
            return content[:marker_position].rstrip()
        marker_position = content.rfind(marker, 0, marker_position)
    signature_positions = [
        position
        for marker in ("\n\nAuthorized Signatory\n", "\n\nSignature:")
        if (position := content.rfind(marker)) >= 0
    ]
    if signature_positions:
        marker_position = min(signature_positions)
        old_footer = content[marker_position:]
        if "Place:" in old_footer and ("Signature:" in old_footer or "Authorized Signatory" in old_footer):
            return content[:marker_position].rstrip()
    return content


def _standard_footer(profile, prep) -> str:
    bid_number = prep.bid_number or prep.bid.bid_number or "Bid number not recorded"
    return "\n\n".join((
        "Declaration\n"
        "I/We declare that the information stated in this document is true and correct to the best of our knowledge and belief. "
        f"The Buyer may verify the details and supporting documents submitted for GeM Bid No. {bid_number}.",
        "\n".join((
            "Authorized Signatory",
            "",
            "Signature:",
            f"Name: {profile.signatory_name or '____________________'}                         Company Seal and Stamp",
            "",
            f"Date: {timezone.localdate().strftime('%d %B %Y')}",
            f"Place: {_place(profile)}",
        )),
    ))


def _with_standard_footer(profile, prep, content: str) -> str:
    """Ensure every generated document ends with exactly one standard footer."""
    content = remove_company_letterhead_footer(content)
    return f"{content.rstrip()}\n\n{_standard_footer(profile, prep)}"


def _table_cell(value) -> str:
    """Keep editable pipe-delimited table rows unambiguous."""
    return str(value if value is not None else "—").replace("|", "/").replace("\n", " ").strip() or "—"


def remove_source_pdf_filename_lines(content: str) -> str:
    """Remove standalone source labels that expose an uploaded PDF filename."""
    return "\n".join(
        line for line in content.splitlines()
        if not re.fullmatch(r"\s*Source:\s*.+\.pdf\s*", line, re.IGNORECASE)
    )


def _recipient_line(prep) -> str:
    """Render the first-page department followed by its organization name."""
    department = (getattr(prep, "buyer_department", "") or "").strip()
    organization = (getattr(prep, "buyer_name", "") or "").strip()
    details = "\n".join(value for value in (department, organization) if value)
    if not details:
        details = (getattr(prep, "beneficiary_details", "") or "").strip()
        if details:
            details = re.sub(r"^To\s*:\s*", "", details, flags=re.IGNORECASE)
    return f"To: {details}" if details else "To:"


def _body(profile, prep, document_type: str) -> str:
    """Generate document body content from template."""
    bid_number = prep.bid_number or prep.bid.bid_number or "Bid number not recorded"
    experience = profile.professional_experience_summary or "No experience statement is recorded in the company profile. Add only details supported by verifiable records."
    evidence = list(profile.documents.order_by("document_type", "title"))
    evidence_lines = [f"{d.title} ({d.get_document_type_display()})" for d in evidence]
    evidence_text = "\n".join(f"- {item}" for item in evidence_lines) or "No company supporting documents are attached to the company profile."

    if document_type == "experience_declaration":
        return "\n\n".join([
            _recipient_line(prep),
            f"Subject: Experience criteria declaration – {bid_number}",
            f"Bid experience requirement recorded for reference: {prep.required_experience_years} year(s)." if prep.required_experience_years is not None else "Verify the experience requirement in the bid before signing.",
            f"Bidder-provided company profile statement: {experience}",
            "Attach relevant contracts, work orders, and completion or acceptance evidence required by the bid. Verify each statement against those records before signing. This draft does not claim that the bid's experience criterion has been met.",
        ])

    if document_type == "past_performance":
        return "\n\n".join([
            _recipient_line(prep),
            f"Subject: Past performance / MSME relaxation request – {bid_number}",
            f"The company profile records Udyam number {profile.udyam_number or 'not provided'} and enterprise category {profile.get_enterprise_type_display()}.",
            "The bidder requests consideration for any MSME relaxation from past performance or prior experience criteria only where this bid permits it and the bidder meets all applicable conditions. Attach current registration and any required performance records. This request does not establish eligibility.",
        ])

    if document_type == "bidder_turnover":
        return "\n\n".join([
            _recipient_line(prep),
            f"Subject: Bidder turnover requirement – {bid_number}",
            f"Bidder turnover threshold recorded for reference: INR {prep.bidder_turnover_threshold} (verify the financial period and calculation basis against the bid)." if prep.bidder_turnover_threshold is not None else "Verify the bidder turnover threshold and financial period in the bid.",
            f"The company profile records Udyam number {profile.udyam_number or 'not provided'} and enterprise category {profile.get_enterprise_type_display()}.",
            "Where this bid permits MSME turnover relaxation, the bidder requests consideration subject to its eligibility and supporting evidence. No turnover amount is certified here. ITR total income is not represented as turnover; provide the financial evidence required by the bid.",
        ])

    if document_type == "msme_turnover_exemption":
        enterprise_type = profile.get_enterprise_type_display()
        return "\n\n".join([
            _recipient_line(prep),
            f"Subject: MSME Turnover Exemption Declaration – {bid_number}",
            (
                f"We, {profile.legal_name or profile.trade_name or '[Company Legal Name]'}, declare that our enterprise is registered as an MSME under Udyam Registration Number {profile.udyam_number or '[Udyam Registration Number]'} and is classified as {enterprise_type}."
            ),
            (
                f"We request exemption from the minimum average annual turnover requirement for this bid, to the extent permitted by the applicable GeM terms and the bid conditions. The turnover threshold recorded for this bid is INR {prep.bidder_turnover_threshold}."
                if prep.bidder_turnover_threshold is not None
                else "We request exemption from the minimum average annual turnover requirement for this bid, to the extent permitted by the applicable GeM terms and the bid conditions."
            ),
            "We confirm that the Udyam registration and enterprise classification are valid on the bid submission date. We understand that this declaration does not waive any other eligibility, experience, technical, or documentary requirement unless the bid expressly permits it.",
            "We will provide the current Udyam certificate and any other supporting documents required by the buyer for verification.",
        ])

    if document_type == "undertaking":
        return "\n\n".join([
            _recipient_line(prep),
            f"Subject: Undertaking – {bid_number}",
            "We hereby undertake that:",
            "1. We have read and understood all terms and conditions of the bid document.",
            "2. We accept all terms and conditions of the bid without any deviation.",
            "3. All information provided in our bid is true and correct to the best of our knowledge.",
            "4. We have not been blacklisted by any Government department/PSU.",
            "5. We will not withdraw or modify our bid after submission.",
            "6. We will execute the contract as per bid terms if awarded.",
            "This undertaking is submitted as part of our bid for the above reference.",
        ])

    if document_type == "declaration":
        return "\n\n".join([
            _recipient_line(prep),
            f"Subject: Declaration of Eligibility and Compliance – {bid_number}",
            "We hereby declare that:",
            "1. Our company is legally constituted and validly existing under the laws of India.",
            "2. We meet all eligibility criteria specified in the bid document.",
            "3. We have not been convicted of any offence involving moral turpitude.",
            "4. No criminal proceedings are pending against the company or its directors.",
            "5. We are not in violation of any statutory requirement.",
            "6. We have the necessary infrastructure and capability to execute the contract.",
            "7. All documents submitted are genuine and authentic.",
            f"8. Our GSTIN is {profile.gstin or 'not provided'}.",
            f"9. Our PAN is {profile.pan or 'not provided'}.",
            "We understand that any false declaration will lead to disqualification and legal action.",
        ])

    if document_type == "authorization_letter":
        return "\n\n".join([
            _recipient_line(prep),
            f"Subject: Authorization Letter – {bid_number}",
            f"We, {profile.legal_name or '[Company Legal Name]'}, hereby authorize Mr./Ms. {profile.signatory_name or '[Authorized Signatory Name]'},",
            f"designated as {profile.signatory_designation or '[Designation]'}, to:",
            "1. Sign and submit the bid documents on our behalf.",
            "2. Negotiate, finalize, and execute the contract.",
            "3. Represent us in all matters related to this bid.",
            "4. Receive communications and correspondences.",
            f"Company: {profile.legal_name or '[Company Legal Name]'}",
            f"Address: {profile.address or '[Company Address]'}",
            f"Contact: {profile.email or '[Email]'}, {profile.phone or '[Phone]'}",
            "This authorization is valid until the completion of the bid process and contract execution.",
        ])

    if document_type == "technical_compliance":
        return "\n\n".join([
            _recipient_line(prep),
            f"Subject: Technical Compliance Statement – {bid_number}",
            "We confirm that our offered products/services fully comply with the technical specifications",
            "and requirements specified in the bid document. Any deviations are listed below:",
            "",
            "Compliance Summary:",
            "All technical requirements have been reviewed against our offer. Items marked 'Complies' meet",
            "or exceed the specified requirements. Items marked 'Needs Review' require bidder verification.",
            "",
            "This statement does not assert compliance; the bidder must verify each item against the final offer.",
        ])

    if document_type == "non_blacklisting_declaration":
        return "\n\n".join([
            _recipient_line(prep),
            f"Subject: Non-Blacklisting Declaration – {bid_number}",
            f"We, {profile.legal_name or '[Company Legal Name]'}, hereby declare that:",
            "",
            "1. We have not been blacklisted/debarred by any Central/State Government department,",
            "   Public Sector Undertaking, or any other Government agency in India.",
            "2. No criminal case is pending against the company or its directors.",
            "3. We have not been convicted of any offence under the Prevention of Corruption Act, 1988",
            "   or any other law for the time being in force.",
            "4. We have not violated the terms of any previous government contract.",
            "",
            "We understand that if this declaration is found to be false, our bid will be rejected",
            "and we may be blacklisted from future government procurement.",
        ])

    if document_type == "turnover_declaration":
        return "\n\n".join([
            _recipient_line(prep),
            f"Subject: Turnover Declaration – {bid_number}",
            f"Bidder turnover threshold: INR {prep.bidder_turnover_threshold if prep.bidder_turnover_threshold is not None else 'Not specified'} (verify against bid).",
            "",
            "We declare our average annual turnover for the last 3 financial years:",
            "",
            "Financial Year 2021-22: INR [REQUIRED FROM USER]",
            "Financial Year 2022-23: INR [REQUIRED FROM USER]",
            "Financial Year 2023-24: INR [REQUIRED FROM USER]",
            "Average Annual Turnover: INR [REQUIRED FROM USER]",
            "",
            "Supporting documents: Audited Balance Sheets / ITR / CA Certificate (upload to company profile).",
            "Note: ITR total income is not represented as turnover. Provide the financial evidence required by the bid.",
        ])

    if document_type == "mse_startup_declaration":
        return "\n\n".join([
            _recipient_line(prep),
            f"Subject: MSE / Startup Declaration – {bid_number}",
            f"Enterprise Status: {'MSME (Udyam: ' + profile.udyam_number + ')' if profile.udyam_number else 'Not registered as MSME'}",
            f"Startup Recognition: {profile.startup_recognition_number or 'Not recognized as Startup'}",
            "",
            "We declare that our company:",
            "1. Is registered as a Micro/Small/Medium Enterprise under the MSMED Act, 2006." if profile.is_msme else "1. Is NOT registered as an MSME.",
            "2. Holds valid Udyam Registration Number: " + (profile.udyam_number or "[REQUIRED FROM USER]"),
            "3. Category: " + (profile.get_enterprise_type_display() if profile.enterprise_type else "[REQUIRED FROM USER]"),
            "4. Is recognized as a Startup by DPIIT: " + ("Yes (Recognition No: " + profile.startup_recognition_number + ")" if profile.startup_recognition_number else "No"),
            "",
            "We request consideration for applicable MSE/Startup benefits as per the bid terms and",
            "Government of India policies (Public Procurement Policy for MSEs, Startup India).",
        ])

    if document_type == "additional_doc_1":
        return "\n\n".join([
            f"Additional Document 1 – BoQ response for {bid_number}",
            "Bidder responses default to Complied in the BoQ table. Verify each response against the final offer and disclose deviations before submission.",
            prep.payment_note or "Payment terms: as specified in the bid and resulting contract.",
        ])

    if document_type == "additional_doc_2":
        return "\n\n".join([
            f"Additional Document 2 – Company supporting documents index for {bid_number}",
            "The following are existing company documents attached to the profile. The source files remain separate and unchanged;",
            "this index does not combine them or certify their validity.",
            evidence_text,
            "Verify the bid's Additional Document 2 requirement and attach only the source evidence it requests.",
        ])

    if document_type == "atc_certificate":
        return "\n\n".join([
            f"ATC certificate supporting documents index for {bid_number}",
            "The exact certificate wording or form requested by the buyer's ATC was not identified in the available bid text.",
            "This page indexes profile evidence only and is not a substitute for a buyer-prescribed certificate or undertaking.",
            evidence_text,
            "Check the ATC and replace or supplement this index with the exact certificate requested by the buyer before submission.",
        ])

    if document_type == "boq_specifications":
        return "\n\n".join([
            _recipient_line(prep),
            f"Subject: Compliance to BoQ Specifications – {bid_number}",
            (
                f"We, M/S {profile.legal_name or profile.trade_name or '[Company Legal Name]'}, submit this "
                "BoQ compliance response for the above GeM bid. The item descriptions, quantities and "
                "specification details below are extracted from available bid documents and are provided "
                "for bidder review."
            ),
            "1. Compliance with BoQ Specifications",
            "Review each extracted item against the final offer and enter the offered specification and supporting evidence in the response table.",
            "2. Quality and Conformity",
            "Confirm applicable technical requirements, quality standards and certifications against the bid before making a compliance statement.",
            "3. Supporting Documents",
            "Attach genuine, verifiable technical literature, certificates, authorizations and other evidence wherever required by the bid or ATC.",
            "4. Delivery / Performance",
            "Confirm the delivery and performance periods against the bid and resulting contract before submission.",
            "5. Non-Conformance",
            "Review the bid and contract terms for the corrective actions required if an offered item or service does not conform.",
            "6. Legal and Contractual Compliance",
            "Review the GeM General Terms and Conditions, applicable ATC, BoQ and technical specifications before signing.",
            "Bidder responses default to Complied. Verify each response against the final offer, correct any deviations and attach supporting evidence before signing. This generated draft is not an independent verification of compliance.",
        ])

    if document_type in ("oem_annual_turnover", "oem_turnover_cover"):
        itr_docs = [d for d in evidence if d.document_type in ("itr", "oem")]
        itr_lines = [f"{d.title}" + (f" (AY {d.assessment_year})" if d.assessment_year else "") for d in itr_docs]
        indexed = "\n".join(f"- {item}" for item in itr_lines) or "No ITR/OEM turnover evidence is attached to the company profile."
        threshold = f"OEM threshold recorded for reference: INR {prep.oem_turnover_threshold}. Verify the required OEM entity and financial period in the bid." if prep.oem_turnover_threshold is not None else "Verify the OEM entity, turnover threshold, and financial period in the bid."
        return "\n\n".join([
            f"OEM annual turnover evidence index – {bid_number}",
            threshold,
            f"OEM name in profile: {profile.oem_name or 'Not recorded; identify the actual OEM before submission.'}",
            indexed,
            "This index is not an ITR, audited statement, turnover certificate, or proof of financial eligibility. ITR income is not represented as turnover. Keep original evidence separate and verify that it belongs to the required OEM.",
        ])

    raise ValueError(f"Unsupported generated document type: {document_type}")


def _source_boq_table_sections(prep) -> list[str]:
    groups = {}
    for item in prep.boq_items.order_by("sort_order", "id"):
        group = groups.setdefault(
            item.source_label or "Bidder-entered BoQ",
            {"headers": [], "items": []},
        )
        for header in (item.source_data or {}):
            if header not in group["headers"]:
                group["headers"].append(header)
        group["items"].append(item)

    sections = []
    for source_label, group in groups.items():
        headers = group["headers"]
        has_response_column = any(source_field_for_header(header) == "bidder_response" for header in headers)
        core_columns = [
            ("description", "Description"),
            ("quantity", "Quantity"),
            ("unit", "Unit"),
        ]
        for field_name, label in core_columns:
            if not any(source_field_for_header(header) == field_name for header in headers):
                headers.append(label)
        if not headers:
            continue
        rows = [
            f"Source BoQ table: {_table_cell(source_label)}",
            " | ".join([*(_table_cell(header) for header in headers), *([] if has_response_column else ["Bidder Response"])]),
        ]
        for item in group["items"]:
            values = editable_source_values(item, headers)
            rows.append(" | ".join([
                *(_table_cell(value) for value in values),
                *([] if has_response_column else [item.bidder_response or "Complied"]),
            ]))
        sections.append("\n".join(rows))
    return sections


def ensure_source_boq_tables(content: str, prep, document_type: str) -> str:
    """Include fetched source tables once in BoQ compliance documents."""
    if document_type != "boq_specifications":
        return content
    # Older saved drafts contained a second, generated response table after
    # the source table. Remove only that table block while retaining any user
    # text that follows it.
    lines = content.splitlines()
    legacy_heading = "Extracted BoQ details and bidder response"
    for index, line in enumerate(lines):
        if line.strip() != legacy_heading:
            continue
        end = index + 1
        while end < len(lines) and lines[end].strip() and "|" in lines[end]:
            end += 1
        del lines[index:end]
        content = "\n".join(lines)
        break
    sections = _source_boq_table_sections(prep)
    if "Source BoQ table:" in content:
        if not sections:
            return content
        source_start = content.index("Source BoQ table:")
        boundaries = [
            position
            for marker in (
                "\n\nExtracted BoQ details and bidder response",
                "\n\nDeclaration\n",
            )
            if (position := content.find(marker, source_start)) >= 0
        ]
        source_end = min(boundaries) if boundaries else len(content)
        prefix = content[:source_start]
        if "Bill of quantities" not in prefix:
            prefix = f"{prefix.rstrip()}\n\nBill of quantities\n\n"
        else:
            prefix = prefix.rstrip() + "\n\n"
        fresh_tables = "\n\n".join(sections)
        return f"{prefix}{fresh_tables}{content[source_end:]}"
    if not sections:
        return content

    source_tables = "\n\n".join(["Bill of quantities", *sections])
    marker = "\n\nExtracted BoQ details and bidder response"
    if marker in content:
        return content.replace(marker, f"\n\n{source_tables}{marker}", 1)
    footer_marker = "\n\nDeclaration\n"
    if footer_marker in content:
        return content.replace(footer_marker, f"\n\n{source_tables}{footer_marker}", 1)
    return f"{content.rstrip()}\n\n{source_tables}"


def editable_document_text(profile, prep, document_type: str, title: str, body: Optional[str] = None) -> str:
    """Build the complete editable text shown in the editor and rendered to PDF."""
    bid_number = prep.bid_number or prep.bid.bid_number or "Bid number not recorded"
    document_body = body if body is not None else _body(profile, prep, document_type)
    if not re.search(r"(?im)^\s*To\s*:", document_body):
        document_body = f"{_recipient_line(prep)}\n\n{document_body}"
    sections = [
        _letterhead(profile, prep, title),
        document_body,
    ]

    if document_type == "boq_specifications":
        source_tables = _source_boq_table_sections(prep)
        if source_tables:
            sections.extend(["Bill of quantities", *source_tables])

    if document_type == "additional_doc_1":
        rows = [
            "BoQ item responses",
            "Item / requirement | Quantity | Unit",
        ]
        items = list(prep.boq_items.all())
        source_headers = []
        for item in items:
            for header in item.source_data:
                normalized_header = header.lower()
                if (
                    header not in source_headers
                    and not any(token in normalized_header for token in (
                        "description", "quantity", "qty", "unit", "uom",
                        "bidder response", "compliance", "offered", "response",
                    ))
                ):
                    source_headers.append(header)
        if source_headers:
            rows[1] += " | Additional extracted details"
        rows[1] += " | Bidder response / evidence"
        if items:
            for item in items:
                response = item.bidder_response or "Complied"
                quantity = item.quantity
                values = [item.description, quantity, item.unit]
                extra_details = "; ".join(
                    f"{header}: {item.source_data[header]}"
                    for header in source_headers
                    if item.source_data.get(header)
                )
                if source_headers:
                    values.append(extra_details)
                values.append(response)
                rows.append(" | ".join(_table_cell(value) for value in values))
        else:
            rows.append("No BoQ items entered | — | — | —")
        sections.append("\n".join(rows))

    if document_type in ("additional_doc_2", "atc_certificate", "oem_annual_turnover"):
        rows = [
            "Company evidence files (separate source documents)",
            "Document | Type | Assessment year | Entity",
        ]
        documents = list(profile.documents.order_by("document_type", "title"))
        if documents:
            for evidence in documents:
                rows.append(" | ".join(_table_cell(value) for value in (
                    evidence.title,
                    evidence.get_document_type_display(),
                    evidence.assessment_year,
                    evidence.entity_name,
                )))
        else:
            rows.append("No profile documents | — | — | Needs Review")
        sections.append("\n".join(rows))

    return _with_standard_footer(profile, prep, "\n\n".join(sections))


def render_document_pdf(profile, prep, document_type: str, title: str, content: str) -> bytes:
    """Render the same complete editable text shown in the document editor."""
    content = normalize_generated_document_text(content)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="DocTitle", parent=styles["Title"], fontSize=15, leading=19, alignment=1, textColor=colors.HexColor("#174d43"), spaceAfter=14))
    styles.add(ParagraphStyle(name="BodyCustom", parent=styles["BodyText"], fontSize=9.5, leading=14, spaceAfter=9, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="SmallCustom", parent=styles["BodyText"], fontSize=8, leading=11, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="TableCustom", parent=styles["BodyText"], fontSize=7.5, leading=9))
    styles.add(ParagraphStyle(name="SignatureLabel", parent=styles["BodyText"], fontSize=8, leading=11, alignment=0, spaceAfter=1))
    styles.add(ParagraphStyle(name="SignatureSealLabel", parent=styles["BodyText"], fontSize=8, leading=11, alignment=1, spaceAfter=1))
    styles.add(ParagraphStyle(name="SectionCustom", parent=styles["Heading2"], fontSize=10.5, leading=14, textColor=colors.HexColor("#174d43"), spaceBefore=7, spaceAfter=5))
    styles.add(ParagraphStyle(name="CompanyName", parent=styles["BodyText"], fontSize=13, leading=16, alignment=1, textColor=colors.HexColor("#174d43"), spaceAfter=3))
    styles.add(ParagraphStyle(name="CompanyDetails", parent=styles["BodyText"], fontSize=8.5, leading=11, alignment=1, spaceAfter=1))
    styles.add(ParagraphStyle(name="LetterheadMeta", parent=styles["BodyText"], fontSize=9, leading=12, alignment=1, spaceAfter=3))

    story = []
    paragraph_lines = []
    title_rendered = False
    letterhead_rendered = False
    signature_enabled = document_type in (profile.signature_document_types or [])
    stamp_enabled = document_type in (profile.stamp_document_types or [])

    def flush_paragraph():
        nonlocal letterhead_rendered, title_rendered
        if not paragraph_lines:
            return
        text = "\n".join(paragraph_lines)
        if not letterhead_rendered and text.splitlines()[0].startswith("M/S "):
            lines = text.splitlines()
            story.append(Paragraph(_e(lines[0]), styles["CompanyName"]))
            if len(lines) > 1:
                story.append(Paragraph("<br/>".join(_e(line) for line in lines[1:]), styles["CompanyDetails"]))
            story.append(HRFlowable(
                width="100%",
                thickness=0.8,
                color=colors.HexColor("#174d43"),
                spaceBefore=3,
                spaceAfter=7,
            ))
            letterhead_rendered = True
        elif not title_rendered:
            story.append(Paragraph(_e(text).replace("\n", "<br/>"), styles["DocTitle"]))
            title_rendered = True
        elif text.strip() in {
            "BoQ item responses",
            "Bill of quantities",
            "Company evidence files (separate source documents)",
            "Declaration",
        }:
            story.append(Paragraph(_e(text), styles["SectionCustom"]))
        elif text.startswith("Name:") and "Company Seal and Stamp" in text:
            name_label, _, _seal_label = text.partition("Company Seal and Stamp")
            labels = Table(
                [[
                    Paragraph(_e(name_label.strip()), styles["SignatureLabel"]),
                    Paragraph("Company Seal and Stamp", styles["SignatureSealLabel"]),
                ]],
                colWidths=[85 * mm, 85 * mm],
                hAlign="LEFT",
            )
            labels.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.append(labels)
        elif text.startswith("Date:") and "Place:" in text:
            date_label, place_label = text.splitlines()[:2]
            details = Table(
                [
                    [Paragraph(_e(date_label), styles["SignatureLabel"]), ""],
                    [Paragraph(_e(place_label), styles["SignatureLabel"]), ""],
                ],
                colWidths=[85 * mm, 85 * mm],
                hAlign="LEFT",
            )
            details.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.append(details)
        elif letterhead_rendered and text.startswith(("GeM Bid No.:", "Date:")):
            story.append(Paragraph(_e(text).replace("\n", "<br/>"), styles["LetterheadMeta"]))
        elif text.strip() == "Authorized Signatory" or text.strip().startswith(("Name:", "Date:", "Place:")):
            story.append(Paragraph(_e(text).replace("\n", "<br/>"), styles["SignatureLabel"]))
        else:
            story.append(Paragraph(_e(text).replace("\n", "<br/>"), styles["BodyCustom"]))
        paragraph_lines.clear()

    lines = (content or "").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            index += 1
            continue

        if stripped.startswith("Source BoQ table:"):
            flush_paragraph()
            story.append(Paragraph(_e(stripped), styles["SectionCustom"]))
            index += 1
            raw_rows = []
            while index < len(lines) and lines[index].strip() and "|" in lines[index]:
                raw_rows.append(lines[index].strip())
                index += 1
            if raw_rows:
                column_count = max(len(raw_rows[0].split("|")), 1)
                font_size = 7.5 if column_count <= 5 else max(5, 37.5 / column_count)
                table_style_name = f"BoQSourceTable{column_count}"
                if table_style_name not in styles.byName:
                    styles.add(ParagraphStyle(
                        name=table_style_name,
                        parent=styles["TableCustom"],
                        fontSize=font_size,
                        leading=font_size + 1.5,
                    ))
                source_table_rows = []
                for row_index, row in enumerate(raw_rows):
                    cells = row.split("|")
                    cells = (cells + [""] * column_count)[:column_count]
                    source_table_rows.append([
                        Paragraph(
                            f"<b>{_e(cell.strip())}</b>" if row_index == 0 else _e(cell.strip()),
                            styles[table_style_name],
                        )
                        for cell in cells
                    ])
                source_table = Table(
                    source_table_rows,
                    colWidths=[170 * mm / column_count] * column_count,
                    repeatRows=1,
                    hAlign="LEFT",
                )
                source_table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f1ee")),
                    ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#b8c8c3")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]))
                story.append(source_table)
            continue

        if stripped.startswith("Item / requirement | Quantity | Unit |") or stripped in {"Document | Type | Assessment year | Entity"}:
            flush_paragraph()
            raw_rows = [stripped]
            index += 1
            while index < len(lines) and lines[index].strip() and "|" in lines[index]:
                raw_rows.append(lines[index].strip())
                index += 1
            rows = [[Paragraph(f"<b>{_e(cell.strip())}</b>", styles["TableCustom"]) for cell in raw_rows[0].split("|")]]
            col_count = len(rows[0])
            for row in raw_rows[1:]:
                cells = row.split("|")[:col_count]
                cells.extend([""] * (col_count - len(cells)))
                rows.append([Paragraph(_e(cell.strip()), styles["TableCustom"]) for cell in cells])
            if raw_rows[0].startswith("Item / requirement") and col_count == 5:
                widths = [50*mm, 20*mm, 18*mm, 38*mm, 44*mm]
            elif raw_rows[0].startswith("Document") and col_count == 4:
                widths = [62*mm, 42*mm, 30*mm, 34*mm]
            else:
                widths = ([76*mm, 22*mm, 20*mm, 50*mm] if col_count == 4 else [170*mm / max(col_count, 1)] * col_count)
            table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f1ee")),
                ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#b8c8c3")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(table)
            continue

        if stripped.startswith("Signature:"):
            flush_paragraph()
            story.append(Paragraph(_e(stripped), styles["SignatureLabel"]))
            signature_data = styled_signature(profile) if signature_enabled and profile.signature_image else b""
            stamp_data = stamp_image_bytes(profile) if stamp_enabled and profile.stamp_image else b""
            if stamp_data or signature_data:
                story.append(SignatureStampBlock(
                    stamp_data,
                    signature_data,
                    float(profile.signature_scale or 1),
                    float(profile.stamp_scale or 1),
                    float(profile.signature_position_x),
                    float(profile.signature_position_y),
                    float(profile.stamp_position_x),
                    float(profile.stamp_position_y),
                ))
            index += 1
            continue

        paragraph_lines.append(line)
        index += 1
    flush_paragraph()

    out = BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm, topMargin=18*mm, bottomMargin=18*mm, title=title, author=profile.legal_name or "")
    doc.build(story)
    return out.getvalue()


def build_document(
    profile,
    prep,
    document_type: str,
    content: Optional[str] = None,
    title_override: Optional[str] = None,
) -> Tuple[str, str, bytes]:
    """Build a document: returns (title, content, pdf_bytes)."""
    title = DOCUMENTS_DICT.get(document_type)
    if document_type.startswith("custom_"):
        title = title_override
    if not title:
        raise ValueError(f"Unsupported generated document type: {document_type}")
    if content is None:
        content = editable_document_text(profile, prep, document_type, title)
    elif re.search(r"(?m)^\s*M/S\b", content, re.IGNORECASE) or (
        len(content.split("\n\n")) >= 4
        and content.split("\n\n")[1].startswith("Bid:")
        and content.split("\n\n")[2].startswith("Buyer:")
        and content.split("\n\n")[3].startswith("Bidder:")
    ):
        content = _letterhead_for_legacy_content(profile, prep, title, content)
    content = normalize_generated_document_text(content)
    content = ensure_source_boq_tables(content, prep, document_type)
    content = _with_standard_footer(profile, prep, content)
    content = remove_source_pdf_filename_lines(content)
    pdf_bytes = render_document_pdf(profile, prep, document_type, title, content)
    return title, content, pdf_bytes


def build_documents(profile, prep) -> List[Tuple[str, str, str, bytes]]:
    """Build all documents for a bid."""
    return [(key, *build_document(profile, prep, key)) for key, _label in DOCUMENTS]
