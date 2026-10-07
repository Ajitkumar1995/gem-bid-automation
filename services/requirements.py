"""
Bid requirements analysis service.
Maps explicit bid text requirements to supported documents and identifies company evidence gaps.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from apps.companies.models import CompanyProfile


@dataclass
class Requirement:
    """A single requirement extracted from a bid."""
    id: str
    document_type: str  # Must match a known document type enum
    title: str
    description: str
    is_required: bool = True
    priority: str = "medium"
    details: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5


@dataclass
class Gap:
    """A gap between what the bid requires and what the company has."""
    document_type: str
    title: str
    missing_fields: List[str] = field(default_factory=list)
    suggested_action: str = ""
    user_input_needed: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RequirementsAnalysis:
    """Result of analyzing bid requirements against company documents."""
    bid_analysis: Dict[str, Any] = field(default_factory=dict)
    requirements: List[Requirement] = field(default_factory=list)
    required_company_documents: List[Dict[str, Any]] = field(default_factory=list)
    matched_documents: List[str] = field(default_factory=list)
    missing_documents: List[str] = field(default_factory=list)
    gaps: Dict[str, Gap] = field(default_factory=dict)
    extraction_confidence: str = "medium"
    notes: str = ""
    extracted_at: datetime = field(default_factory=datetime.now)
    has_unverified_data: bool = False  # Set True if any data was guessed


# Document type definitions for generation
DOCUMENT_TYPE_DEFS = {
    "experience_declaration": {
        "title": "Experience Declaration",
        "description": "Declaration of past work experience meeting the bid's experience criteria."
    },
    "past_performance": {
        "title": "Past Performance / MSME Relaxation Request",
        "description": "Past performance evidence and MSME relaxation request."
    },
    "bidder_turnover": {
        "title": "Bidder Turnover Declaration",
        "description": "Bidder's average annual turnover declaration."
    },
    "undertaking": {
        "title": "Undertaking",
        "description": "General undertaking as required by the bid terms."
    },
    "declaration": {
        "title": "Declaration",
        "description": "Bidder declaration of eligibility and compliance."
    },
    "authorization_letter": {
        "title": "Authorization Letter",
        "description": "Authorization letter from company to authorized signatory."
    },
    "technical_compliance": {
        "title": "Technical Compliance Statement",
        "description": "Statement of technical compliance with bid requirements."
    },
    "non_blacklisting_declaration": {
        "title": "Non-Blacklisting Declaration",
        "description": "Declaration that the company is not blacklisted by any government body."
    },
    "turnover_declaration": {
        "title": "Turnover Declaration",
        "description": "Detailed turnover declaration supporting financial criteria."
    },
    "mse_startup_declaration": {
        "title": "MSE / Startup Declaration",
        "description": "Declaration of Micro, Small or Startup enterprise status."
    },
    "additional_doc_1": {
        "title": "Additional Document 1",
        "description": "Additional requested document (usually BoQ response)."
    },
    "additional_doc_2": {
        "title": "Additional Document 2",
        "description": "Additional requested document (usually supporting documents index)."
    },
    "atc_certificate": {
        "title": "ATC Supporting Documents",
        "description": "Documents supporting the Award/Technical Certificate requirements."
    },
    "boq_specifications": {
        "title": "Compliance to BoQ Specifications",
        "description": "Compliance response to Bill of Quantities specifications."
    },
    "oem_annual_turnover": {
        "title": "OEM Annual Turnover Evidence",
        "description": "Original Equipment Manufacturer annual turnover evidence."
    },
}

# Company document types that can satisfy requirements
COMPANY_DOC_SATISFIES = {
    "experience_declaration": ["experience"],
    "past_performance": ["experience", "work_order"],
    "bidder_turnover": ["itr", "turnover"],
    "turnover_declaration": ["itr", "turnover"],
    "mse_startup_declaration": ["udyam", "startup"],
    "oem_annual_turnover": ["oem", "itr"],
}

# Company document types that should be included as reference
COMPANY_DOC_REFERENCES = ["udyam", "gst", "pan", "startup", "oem", "experience", "work_order", "turnover", "itr", "other"]

LOCAL_DOCUMENT_RULES = {
    "experience_declaration": (
        r"\byears?\s+of\s+(?:past|relevant)\s+experience\s+required\b",
        r"\bexperience\s+criteria\b",
        r"\bsimilar\s+(?:work|project|supply)\s+experience\b",
    ),
    "past_performance": (
        r"\bpast\s+performance\b",
        r"\bperformance\s+certificate\b",
    ),
    "bidder_turnover": (
        r"\b(?:minimum|average|annual)\s+(?:average\s+)?(?:annual\s+)?turnover\s+of\s+the\s+bidder\b",
        r"\bbidder\s+turnover\s+(?:certificate|evidence|declaration)\b",
    ),
    "undertaking": (
        r"\b(?:submit|provide|upload)\s+(?:an?\s+)?undertaking\b",
        r"\bundertaking\s+(?:is\s+)?required\b",
    ),
    "authorization_letter": (
        r"\bauthori[sz]ation\s+letter\b",
        r"\bauthori[sz]ed\s+signatory\s+letter\b",
    ),
    "technical_compliance": (
        r"\btechnical\s+compliance\b",
        r"\bcompliance\s+(?:statement|to the specifications)\b",
    ),
    "non_blacklisting_declaration": (
        r"\bnon[- ]blacklisting\b",
        r"\bnot\s+blacklisted\b",
    ),
    "turnover_declaration": (
        r"\bturnover\s+declaration\b",
        r"\baverage\s+annual\s+turnover\s+certificate\b",
    ),
    "mse_startup_declaration": (
        r"\b(?:mse|msme|startup)\s+(?:status\s+)?declaration\b",
        r"\b(?:mse|msme|startup)\s+(?:exemption|relaxation)\b",
    ),
    "atc_certificate": (
        r"\bATC\s+(?:certificate|supporting\s+documents?)\b",
        r"\bcertificate\s+as\s+per\s+(?:the\s+)?ATC\b",
    ),
    "boq_specifications": (
        r"\b(?:boq|bill\s+of\s+quantities)\s+(?:specification|compliance)\b",
        r"\bcompliance\s+to\s+(?:the\s+)?(?:boq|bill\s+of\s+quantities)\b",
    ),
    "oem_annual_turnover": (
        r"\bOEM\s+(?:average\s+)?annual\s+turnover\b",
        r"\bannual\s+turnover\s+(?:of\s+the\s+)?OEM\b",
    ),
}

LOCAL_COMPANY_DOCUMENT_RULES = {
    "udyam": (r"\b(?:udyam|msme)\s+(?:registration\s+)?certificate\b",),
    "gst": (r"\bGST\s+(?:registration\s+)?certificate\b", r"\bproof\s+of\s+GST\s+registration\b"),
    "pan": (r"\bPAN\s+card\b", r"\bcopy\s+of\s+(?:the\s+)?PAN\b"),
    "itr": (r"\b(?:ITR|income[- ]tax\s+return|audited\s+financial\s+statements?)\b",),
    "experience": (r"\b(?:work\s+orders?|experience\s+certificates?|completion\s+certificates?)\b",),
    "oem": (r"\bOEM\s+authori[sz]ation\b", r"\bmanufacturer\s+authori[sz]ation\b"),
}


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def analyze_requirements(pdf_text: str) -> RequirementsAnalysis:
    """Conservatively match explicitly named requirements from extracted bid text."""
    result = RequirementsAnalysis(
        extraction_confidence="low",
        has_unverified_data=True,
    )
    result.requirements = [
        Requirement(
            id=f"local-{document_type}",
            document_type=document_type,
            title=DOCUMENT_TYPE_DEFS[document_type]["title"],
            description=DOCUMENT_TYPE_DEFS[document_type]["description"],
            priority="medium",
            confidence=0.4,
        )
        for document_type, patterns in LOCAL_DOCUMENT_RULES.items()
        if _matches_any(pdf_text, patterns)
    ]
    result.required_company_documents = [
        {
            "document_type": document_type,
            "title": f"{document_type.replace('_', ' ').title()} supporting document",
            "is_required": True,
            "description": "The bid text appears to request this company document; verify the exact clause.",
        }
        for document_type, patterns in LOCAL_COMPANY_DOCUMENT_RULES.items()
        if _matches_any(pdf_text, patterns)
    ]
    guidance = "Requirements were matched locally from explicit text phrases; verify them against the original bid before preparing documents."
    if not result.requirements:
        guidance += " No supported document requirement could be confidently matched, so review the full template list."
    result.notes = guidance
    return result


def build_requirements_metadata(pdf_text: str, profile: Optional[CompanyProfile]) -> Dict[str, Any]:
    """Build the persisted, template-ready requirement summary from one bid's text."""
    analysis = analyze_requirements(pdf_text)
    matched = match_company_documents(analysis.requirements, profile)
    available_company_types = set(profile.documents.values_list("document_type", flat=True)) if profile else set()
    missing_company_documents = [
        item["title"]
        for item in analysis.required_company_documents
        if item["is_required"] and item["document_type"] not in available_company_types
    ]
    return {
        "bid_analysis": analysis.bid_analysis,
        "required_documents": [
            {
                "document_type": requirement.document_type,
                "title": requirement.title,
                "description": requirement.description,
                "is_required": requirement.is_required,
                "priority": requirement.priority,
                "details": requirement.details,
            }
            for requirement in analysis.requirements
        ],
        "required_company_documents": analysis.required_company_documents,
        "missing_company_documents": missing_company_documents,
        "matched_company_documents": matched["matched"],
        "generated_document_evidence_gaps": matched["missing"],
        "company_document_gaps": {
            document_type: {
                "title": gap.title,
                "missing_fields": gap.missing_fields,
                "suggested_action": gap.suggested_action,
            }
            for document_type, gap in matched["gaps"].items()
        },
        "extraction_confidence": analysis.extraction_confidence,
        "notes": analysis.notes,
        "has_unverified_data": analysis.has_unverified_data,
    }


def match_company_documents(requirements: List[Requirement], profile: Optional[CompanyProfile]) -> Dict[str, Any]:
    """
    Match requirements against company documents.
    Returns matched, missing, and gaps.
    """
    matched: Set[str] = set()
    missing: Set[str] = set()
    gaps: Dict[str, Gap] = {}

    if not profile:
        for req in requirements:
            missing.add(req.document_type)
        return {"matched": [], "missing": list(missing), "gaps": gaps}

    company_doc_types = set()
    for doc in profile.documents.all():
        company_doc_types.add(doc.document_type)
        # Add derived types
        if doc.document_type == "experience":
            company_doc_types.add("work_order")
        elif doc.document_type == "oem":
            company_doc_types.add("itr")
        elif doc.document_type in ("udyam", "other") and profile.is_msme:
            company_doc_types.add("msme")

    for req in requirements:
        satisfiers = set(COMPANY_DOC_SATISFIES.get(req.document_type, []))
        if not company_doc_types.intersection(satisfiers):
            missing.add(req.document_type)
            gaps[req.document_type] = Gap(
                document_type=req.document_type,
                title=DOCUMENT_TYPE_DEFS.get(req.document_type, {}).get("title", req.title),
                missing_fields=["No supporting company documents found"],
                suggested_action=f"Upload a {req.description.lower()} to the company profile.",
            )
        else:
            matched.add(req.document_type)

    return {"matched": sorted(matched), "missing": sorted(missing), "gaps": gaps}
