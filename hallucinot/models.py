from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class VerificationCheck:
    field: str
    status: str
    expected: str | None = None
    actual: str | None = None
    summary: str = ""


@dataclass(slots=True)
class IdReference:
    raw_text: str
    pin_cite_text: str | None = None
    pin_cite_page: str | None = None
    start_index: int = 0
    end_index: int = 0
    status: str = "not_checked"
    summary: str = ""


@dataclass(slots=True)
class CitationRecord:
    raw_text: str
    normalized_text: str
    category: str
    start_index: int
    end_index: int
    extracted_case_name: str | None = None
    quote_snippet: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    id_references: list[IdReference] = field(default_factory=list)


@dataclass(slots=True)
class VerificationCandidate:
    case_name: str
    date_filed: str | None
    court: str | None
    matched_citations: list[str]
    url: str | None


@dataclass(slots=True)
class VerificationResult:
    citation: CitationRecord
    status: str
    summary: str
    matched: bool
    candidates: list[VerificationCandidate] = field(default_factory=list)
    checks: list[VerificationCheck] = field(default_factory=list)
