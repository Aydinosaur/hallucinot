from __future__ import annotations

import re

from eyecite import get_citations
from eyecite.models import CaseCitation, FullCaseCitation, IdCitation

from hallucinot.models import CitationRecord, IdReference

QUOTE_WINDOW = 300
CASE_NAME_PATTERN = re.compile(
    r"([A-Z][A-Za-z0-9&.,'() -]{1,140}?)\s+v\.\s+([A-Z][A-Za-z0-9&.,'() -]{1,160}?)(?=(?:,\s*\d+\s+[A-Z]|$))"
)


def extract_citations(text: str, styled_ranges: list[tuple[int, int]] | None = None) -> list[CitationRecord]:
    citations: list[CitationRecord] = []
    seen: set[tuple[str, int, int]] = set()
    previous_full_citation: CitationRecord | None = None

    for citation in get_citations(text):
        if not isinstance(citation, (CaseCitation, IdCitation)):
            previous_full_citation = None
            continue

        start, end = citation.full_span()
        if not isinstance(citation, IdCitation):
            start = _expand_case_start(text, start, end, styled_ranges or [])
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
        extracted_case_name = _extract_case_name(citation, text, start, end, styled_ranges or [])
        raw_text = _clean_raw_case_text(raw_text, extracted_case_name)
        extracted_case_name = _extract_case_name_from_metadata(raw_text, start, styled_ranges or []) or extracted_case_name

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


def _extract_case_name(
    citation: object,
    text: str,
    start: int,
    end: int,
    styled_ranges: list[tuple[int, int]],
) -> str | None:
    context_text, context_start = _context_slice(text, start, end)
    candidates = [
        _extract_case_name_from_citation_metadata(citation),
        _extract_case_name_from_metadata(text[start:end], start, styled_ranges),
        _extract_case_name_from_window(text, start, end, styled_ranges),
        _extract_case_name_from_sentence(context_text, context_start, styled_ranges),
    ]
    usable = [candidate for candidate in candidates if candidate]
    if not usable:
        return None
    return max(usable, key=_case_name_score)


def _extract_case_name_from_metadata(
    raw_text: str,
    offset: int = 0,
    styled_ranges: list[tuple[int, int]] | None = None,
) -> str | None:
    candidate = _extract_best_case_name(raw_text, offset, styled_ranges or [])
    return _clean_case_name(candidate) if candidate else None


def _extract_case_name_from_citation_metadata(citation: object) -> str | None:
    metadata = getattr(citation, "metadata", None)
    plaintiff = getattr(metadata, "plaintiff", None)
    defendant = getattr(metadata, "defendant", None)
    if not plaintiff or not defendant:
        return None
    return _clean_case_name(f"{plaintiff} v. {defendant}")


def _extract_case_name_from_window(
    text: str,
    start: int,
    end: int,
    styled_ranges: list[tuple[int, int]],
) -> str | None:
    window_start = max(0, start - 180)
    window = text[window_start:min(len(text), end + 40)]
    return _extract_case_name_from_sentence(window, window_start, styled_ranges)


def _context_slice(text: str, start: int, end: int) -> tuple[str, int]:
    left_bound = max(text.rfind(".", 0, start), text.rfind(";", 0, start), text.rfind("\n", 0, start))
    right_candidates = [
        idx for idx in (text.find(".", end), text.find(";", end), text.find("\n", end)) if idx != -1
    ]
    right_bound = min(right_candidates) if right_candidates else min(len(text), end + 240)
    slice_start = max(0, left_bound + 1)
    return text[slice_start:right_bound], slice_start


def _extract_case_name_from_sentence(
    sentence: str,
    offset: int = 0,
    styled_ranges: list[tuple[int, int]] | None = None,
) -> str | None:
    candidate = _extract_best_case_name(sentence, offset, styled_ranges or [])
    return _clean_case_name(candidate) if candidate else None


def _clean_case_name(value: str) -> str | None:
    candidate = re.sub(r"\s+", " ", value).strip(" ,.;()")
    candidate = re.sub(r"^.*\b(In|See|Cf\.|But see|Compare|But cf\.)\s+", "", candidate, flags=re.IGNORECASE)
    extracted = _extract_best_case_name(candidate)
    if extracted:
        candidate = extracted
    candidate = re.sub(r",?\s+\d+\s+[A-Z][A-Za-z0-9. ]+\s+\d+.*$", "", candidate)
    return candidate.strip() or None


def _extract_best_case_name(text: str, offset: int = 0, styled_ranges: list[tuple[int, int]] | None = None) -> str | None:
    matches = list(CASE_NAME_PATTERN.finditer(text))
    if not matches:
        fallback = list(re.finditer(r"([A-Z][A-Za-z0-9&.,'() -]{1,140}?)\s+v\.\s+([A-Z][A-Za-z0-9&.,'() -]{1,160})", text))
        if not fallback:
            return None
        matches = fallback

    best_match = max(matches, key=lambda match: _case_match_score(match, offset, styled_ranges or []))
    return f"{best_match.group(1)} v. {best_match.group(2)}"


def _clean_raw_case_text(raw_text: str, extracted_case_name: str | None) -> str:
    match = None
    matches = list(CASE_NAME_PATTERN.finditer(raw_text))
    if matches:
        match = matches[-1]
    elif extracted_case_name:
        case_index = raw_text.find(extracted_case_name)
        if case_index != -1:
            return raw_text[case_index:].strip()

    if match is None:
        return raw_text.strip()

    return raw_text[match.start():].strip()


def _expand_case_start(text: str, start: int, end: int, styled_ranges: list[tuple[int, int]]) -> int:
    if not styled_ranges:
        return start

    nearby = [span for span in styled_ranges if span[1] >= start - 24 and span[0] <= end]
    if not nearby:
        return start

    cluster: list[tuple[int, int]] = []
    for span_start, span_end in nearby:
        if span_end >= start and span_start <= end:
            cluster.append((span_start, span_end))

    if not cluster:
        for span_start, span_end in nearby:
            gap_text = text[span_end:start]
            if span_end < start and len(gap_text) <= 24 and not re.search(r"[.;:!?]", gap_text):
                cluster.append((span_start, span_end))

    if not cluster:
        return start

    cluster.sort()
    expanded_start = min(span_start for span_start, _ in cluster)
    current_start = expanded_start

    while True:
        previous = None
        for span_start, span_end in styled_ranges:
            if span_end <= current_start:
                gap_text = text[span_end:current_start]
                if len(gap_text) <= 6 and not re.search(r"[;:!?]", gap_text):
                    previous = (span_start, span_end)
        if previous is None:
            break
        if previous[0] >= current_start:
            break
        current_start = previous[0]

    return current_start


def _case_match_score(match: re.Match[str], offset: int, styled_ranges: list[tuple[int, int]]) -> tuple[int, int, int]:
    candidate = f"{match.group(1)} v. {match.group(2)}"
    absolute_start = offset + match.start()
    absolute_end = offset + match.end()
    styled_characters = _styled_character_count(absolute_start, absolute_end, styled_ranges)
    return (styled_characters, *_case_name_score(candidate))


def _styled_character_count(start: int, end: int, styled_ranges: list[tuple[int, int]]) -> int:
    total = 0
    for styled_start, styled_end in styled_ranges:
        overlap_start = max(start, styled_start)
        overlap_end = min(end, styled_end)
        if overlap_start < overlap_end:
            total += overlap_end - overlap_start
    return total


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
