from __future__ import annotations

import re

from eyecite import get_citations
from eyecite.models import FullCaseCitation, IdCitation

from hallucinot.models import CitationRecord, IdReference

QUOTE_WINDOW = 300


def extract_citations(text: str) -> list[CitationRecord]:
    citations: list[CitationRecord] = []
    seen: set[tuple[str, int, int]] = set()
    previous_full_citation: CitationRecord | None = None

    for citation in get_citations(text):
        start, end = citation.full_span()
        raw_text = text[start:end]
        span_key = (raw_text.strip(), start, end)
        if span_key in seen:
            continue
        seen.add(span_key)

        if isinstance(citation, IdCitation):
            if previous_full_citation is not None:
                previous_full_citation.id_references.append(_build_id_reference(citation, raw_text, start, end))
            continue

        normalized_text = _normalize_citation_text(citation)
        extracted_case_name = _extract_case_name(citation, text, start, end)

        metadata = _extract_metadata(citation)
        if "year" not in metadata:
            contextual_year = _extract_year_from_context(text, end)
            if contextual_year:
                metadata["year"] = contextual_year

        record = CitationRecord(
            raw_text=raw_text,
            normalized_text=normalized_text,
            category=type(citation).__name__,
            start_index=start,
            end_index=end,
            extracted_case_name=extracted_case_name,
            quote_snippet=_find_quote_near_citation(text, start, end),
            metadata=metadata,
        )
        citations.append(record)
        previous_full_citation = record

    return sorted(citations, key=lambda item: item.start_index)


def _normalize_citation_text(citation: object) -> str:
    corrected = getattr(citation, "corrected_citation", lambda: None)()
    if corrected:
        return corrected
    return citation.matched_text()


def _extract_metadata(citation: object) -> dict[str, str]:
    metadata: dict[str, str] = {}
    groups = getattr(citation, "groups", {}) or {}
    for key in ("volume", "reporter", "page"):
        value = groups.get(key)
        if value:
            metadata[key] = str(value)

    pin_cite = getattr(getattr(citation, "metadata", None), "pin_cite", None)
    if pin_cite:
        metadata["pin_cite"] = str(pin_cite)
        pin_cite_page = _extract_page_number(pin_cite)
        if pin_cite_page:
            metadata["pin_cite_page"] = pin_cite_page

    if isinstance(citation, FullCaseCitation):
        year = getattr(citation, "year", None)
        court = getattr(citation, "court", None)
        if year:
            metadata["year"] = str(year)
        if court:
            metadata["court"] = str(court)

    return metadata


def _find_quote_near_citation(text: str, start: int, end: int) -> str | None:
    window_start = max(0, start - QUOTE_WINDOW)
    window_end = min(len(text), end + QUOTE_WINDOW)
    window = text[window_start:window_end]

    quoted_segments = re.findall(r"[\"“]([^\"”]{12,400})[\"”]", window)
    if not quoted_segments:
        return None

    snippet = quoted_segments[-1].strip()
    return snippet if snippet else None


def _extract_case_name(citation: object, text: str, start: int, end: int) -> str | None:
    candidates = [
        _extract_case_name_from_citation_metadata(citation),
        _extract_case_name_from_metadata(text[start:end]),
        _extract_case_name_from_window(text, start, end),
        _extract_case_name_from_sentence(_context_slice(text, start, end)),
    ]
    usable = [candidate for candidate in candidates if candidate]
    if not usable:
        return None
    return max(usable, key=_case_name_score)


def _extract_case_name_from_metadata(raw_text: str) -> str | None:
    match = re.search(
        r"([A-Z][A-Za-z0-9&.,' -]{1,120}\s+v\.\s+[A-Z][A-Za-z0-9&.,' -]{1,120})",
        raw_text,
    )
    if not match:
        return None
    return _clean_case_name(match.group(1))


def _extract_case_name_from_citation_metadata(citation: object) -> str | None:
    metadata = getattr(citation, "metadata", None)
    plaintiff = getattr(metadata, "plaintiff", None)
    defendant = getattr(metadata, "defendant", None)
    if not plaintiff or not defendant:
        return None
    return _clean_case_name(f"{plaintiff} v. {defendant}")


def _extract_case_name_from_window(text: str, start: int, end: int) -> str | None:
    window = text[max(0, start - 180):min(len(text), end + 40)]
    return _extract_case_name_from_sentence(window)


def _context_slice(text: str, start: int, end: int) -> str:
    left_bound = max(text.rfind(".", 0, start), text.rfind(";", 0, start), text.rfind("\n", 0, start))
    right_candidates = [
        idx for idx in (text.find(".", end), text.find(";", end), text.find("\n", end)) if idx != -1
    ]
    right_bound = min(right_candidates) if right_candidates else min(len(text), end + 240)
    return text[max(0, left_bound + 1):right_bound]


def _extract_case_name_from_sentence(sentence: str) -> str | None:
    patterns = [
        r"([A-Z][A-Za-z0-9&.,' -]{1,120}?\s+v\.\s+[A-Z][A-Za-z0-9&.,' -]{1,120}?)(?=,\s*\d+\s+[A-Z])",
        r"([A-Z][A-Za-z0-9&.,' -]{1,120}?\s+v\.\s+[A-Z][A-Za-z0-9&.,' -]{1,120}?)",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, sentence)
        if matches:
            return _clean_case_name(matches[-1])
    return None


def _clean_case_name(value: str) -> str | None:
    candidate = re.sub(r"\s+", " ", value).strip(" ,.;()")
    candidate = re.sub(r"^.*\b(In|See|Cf\.|But see|Compare|But cf\.)\s+", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r",?\s+\d+\s+[A-Z][A-Za-z0-9. ]+\s+\d+.*$", "", candidate)
    return candidate.strip() or None


def _case_name_score(value: str) -> tuple[int, int]:
    abbreviation_penalty = sum(value.count(token) for token in ("Servs.", "Sys.", "Corp.", "Co.", "Inc."))
    digit_penalty = sum(character.isdigit() for character in value)
    return (len(value) - digit_penalty * 8, -abbreviation_penalty)


def _build_id_reference(citation: IdCitation, raw_text: str, start: int, end: int) -> IdReference:
    pin_cite_text = getattr(getattr(citation, "metadata", None), "pin_cite", None)
    return IdReference(
        raw_text=raw_text,
        pin_cite_text=str(pin_cite_text) if pin_cite_text else None,
        pin_cite_page=_extract_page_number(pin_cite_text) if pin_cite_text else None,
        start_index=start,
        end_index=end,
    )


def _extract_page_number(pin_cite: object) -> str | None:
    if pin_cite is None:
        return None
    match = re.search(r"(\d+)", str(pin_cite))
    if not match:
        return None
    return match.group(1)


def _extract_year_from_context(text: str, end: int) -> str | None:
    lookahead = text[end:min(len(text), end + 80)]
    match = re.search(r"\((?:[^()]*?)((?:19|20)\d{2})(?:[^()]*)\)", lookahead)
    if match:
        return match.group(1)
    fallback = re.search(r"\b(19|20)\d{2}\b", lookahead)
    if fallback:
        return fallback.group(0)
    return None
