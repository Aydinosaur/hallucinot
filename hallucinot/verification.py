from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod

import requests

from hallucinot.config import get_courtlistener_token
from hallucinot.models import CitationRecord, VerificationCandidate, VerificationCheck, VerificationResult


class CitationVerifier(ABC):
    name: str

    @abstractmethod
    def verify(self, citation: CitationRecord) -> VerificationResult:
        raise NotImplementedError

    def verify_all(self, citations: list[CitationRecord], text: str) -> list[VerificationResult]:
        return [self.verify(citation) for citation in citations]


class DemoVerifier(CitationVerifier):
    name = "Demo"

    def verify(self, citation: CitationRecord) -> VerificationResult:
        _check_id_references(citation, matched=False)
        return VerificationResult(
            citation=citation,
            status="not_checked",
            matched=False,
            summary="Demo mode only extracted the citation. Configure CourtListener to verify against an external database.",
            checks=[
                VerificationCheck(
                    field="citation",
                    status="not_checked",
                    expected=citation.normalized_text,
                    summary="The citation was extracted, but no external verification was attempted.",
                )
            ],
        )


class CourtListenerVerifier(CitationVerifier):
    name = "CourtListener"
    endpoint = "https://www.courtlistener.com/api/rest/v4/citation-lookup/"

    def __init__(self, api_token: str) -> None:
        self.api_token = api_token

    def verify(self, citation: CitationRecord) -> VerificationResult:
        response = requests.post(
            self.endpoint,
            headers={"Authorization": f"Token {self.api_token}"},
            data=_lookup_payload(citation),
            timeout=30,
        )
        response.raise_for_status()
        results = response.json()
        if not isinstance(results, list) or not results:
            _check_id_references(citation, matched=False)
            return VerificationResult(
                citation=citation,
                status="not_found",
                matched=False,
                summary="No matching citation record was returned.",
                checks=_build_missing_citation_checks(citation),
            )

        return _result_from_lookup_item(citation, results[0])

    def verify_all(self, citations: list[CitationRecord], text: str) -> list[VerificationResult]:
        if not citations:
            return []

        response = requests.post(
            self.endpoint,
            headers={"Authorization": f"Token {self.api_token}"},
            data={"text": text},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("CourtListener returned an unexpected response payload.")

        items_by_citation = _index_lookup_items(payload)
        results: list[VerificationResult] = []
        for citation in citations:
            item = _find_lookup_item(citation, items_by_citation)
            if item is None:
                _check_id_references(citation, matched=False)
                results.append(
                    VerificationResult(
                        citation=citation,
                        status="not_found",
                        matched=False,
                        summary="CourtListener did not return a lookup result for this citation from the uploaded text.",
                        checks=_build_missing_citation_checks(citation),
                    )
                )
                continue
            results.append(_result_from_lookup_item(citation, item))
        return results


def build_verifier(mode: str, api_token: str | None = None) -> CitationVerifier:
    if mode == "CourtListener":
        token = (api_token or get_courtlistener_token() or os.getenv("COURTLISTENER_API_TOKEN", "")).strip()
        if token:
            return CourtListenerVerifier(token)
    return DemoVerifier()


def _lookup_payload(citation: CitationRecord) -> dict[str, str]:
    volume = citation.metadata.get("volume")
    reporter = citation.metadata.get("reporter")
    page = citation.metadata.get("page")
    if volume and reporter and page:
        return {"volume": volume, "reporter": reporter, "page": page}
    return {"text": citation.normalized_text}


def _index_lookup_items(items: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for item in items:
        keys = {str(item.get("citation", "")).strip()}
        for normalized in item.get("normalized_citations", []) or []:
            keys.add(str(normalized).strip())
        for key in keys:
            if not key:
                continue
            index.setdefault(key.casefold(), []).append(item)
    return index


def _find_lookup_item(citation: CitationRecord, items_by_citation: dict[str, list[dict]]) -> dict | None:
    candidates = []
    for key in (citation.normalized_text, citation.raw_text):
        if not key:
            continue
        candidates.extend(items_by_citation.get(key.casefold(), []))

    if not candidates:
        volume = citation.metadata.get("volume")
        reporter = citation.metadata.get("reporter")
        page = citation.metadata.get("page")
        if volume and reporter and page:
            triad = f"{volume} {reporter} {page}".casefold()
            candidates.extend(items_by_citation.get(triad, []))

    if not candidates:
        return None

    if len(candidates) == 1:
        return candidates[0]

    for item in candidates:
        normalized = {str(value).casefold() for value in item.get("normalized_citations", []) or []}
        if citation.normalized_text.casefold() in normalized:
            return item
    return candidates[0]


def _result_from_lookup_item(citation: CitationRecord, item: dict) -> VerificationResult:
    status_code = item.get("status")
    clusters = item.get("clusters", [])
    candidates = [_cluster_to_candidate(cluster) for cluster in clusters]
    checks = _build_checks(citation, candidates)
    matched = all(check.status == "matched" for check in checks if check.status != "not_provided")
    _check_id_references(citation, matched=matched)
    summary = _build_summary(status_code, matched, len(candidates), item.get("error_message", ""))
    return VerificationResult(
        citation=citation,
        status=_map_status(status_code, matched),
        matched=matched,
        summary=summary,
        candidates=candidates,
        checks=checks,
    )


def _cluster_to_candidate(cluster: dict) -> VerificationCandidate:
    citations = cluster.get("citations", []) or []
    matched_citations = [
        " ".join(
            part
            for part in (
                str(citation.get("volume", "")).strip(),
                str(citation.get("reporter", "")).strip(),
                str(citation.get("page", "")).strip(),
            )
            if part
        )
        for citation in citations
    ]
    opinion_url = cluster.get("absolute_url")
    if opinion_url and opinion_url.startswith("/"):
        opinion_url = f"https://www.courtlistener.com{opinion_url}"

    return VerificationCandidate(
        case_name=cluster.get("case_name", "Unknown case"),
        date_filed=cluster.get("date_filed"),
        court=_extract_court_name(cluster),
        matched_citations=[item for item in matched_citations if item],
        url=opinion_url,
    )


def _extract_court_name(cluster: dict) -> str | None:
    docket = cluster.get("docket")
    if isinstance(docket, dict):
        court = docket.get("court")
        if isinstance(court, dict):
            return court.get("full_name") or court.get("short_name")
    return None


def _build_missing_citation_checks(citation: CitationRecord) -> list[VerificationCheck]:
    return [
        VerificationCheck(
            field="citation",
            status="mismatched",
            expected=citation.normalized_text,
            summary="No CourtListener result matched this volume-reporter-page citation.",
        ),
        VerificationCheck(
            field="case_name",
            status="not_checked",
            expected=citation.extracted_case_name,
            summary="Case name was not checked because the citation itself did not resolve.",
        ),
        VerificationCheck(
            field="date",
            status="not_checked",
            expected=citation.metadata.get("year"),
            summary="Date was not checked because the citation itself did not resolve.",
        ),
    ]


def _build_checks(citation: CitationRecord, candidates: list[VerificationCandidate]) -> list[VerificationCheck]:
    if not candidates:
        return _build_missing_citation_checks(citation)

    best = candidates[0]
    citation_matched = any(citation.normalized_text.casefold() == item.casefold() for item in best.matched_citations)
    checks = [
        VerificationCheck(
            field="citation",
            status="matched" if citation_matched else "mismatched",
            expected=citation.normalized_text,
            actual=", ".join(best.matched_citations) if best.matched_citations else None,
            summary=(
                "Volume-reporter-page matched a CourtListener citation."
                if citation_matched
                else "CourtListener returned a candidate, but the exact volume-reporter-page did not match."
            ),
        )
    ]

    expected_case_name = citation.extracted_case_name
    name_matched = _names_compatible(expected_case_name or "", best.case_name) if expected_case_name else True
    checks.append(
        VerificationCheck(
            field="case_name",
            status="matched" if name_matched else "mismatched",
            expected=expected_case_name,
            actual=best.case_name,
            summary=(
                "Case name in the document is compatible with the matched CourtListener case."
                if name_matched
                else "Case name in the document does not match the CourtListener case caption closely enough."
            ),
        )
    )

    expected_year = citation.metadata.get("year")
    actual_year = best.date_filed[:4] if best.date_filed else None
    if expected_year:
        date_matched = actual_year == expected_year
        checks.append(
            VerificationCheck(
                field="date",
                status="matched" if date_matched else "mismatched",
                expected=expected_year,
                actual=actual_year,
                summary=(
                    "The year in the document matches the CourtListener filing year."
                    if date_matched
                    else "The year in the document does not match the CourtListener filing year."
                ),
            )
        )
    else:
        checks.append(
            VerificationCheck(
                field="date",
                status="not_provided",
                actual=actual_year,
                summary="No year was provided in the document citation, so date matching was skipped.",
            )
        )

    return checks


def _names_compatible(expected_case_name: str, candidate_case_name: str) -> bool:
    expected = _normalize_case_name(expected_case_name)
    candidate = _normalize_case_name(candidate_case_name)
    if not expected or not candidate:
        return True
    if expected in candidate or candidate in expected:
        return True

    expected_tokens = _meaningful_tokens(expected)
    candidate_tokens = _meaningful_tokens(candidate)
    if not expected_tokens or not candidate_tokens:
        return True

    overlap = expected_tokens & candidate_tokens
    shorter_len = min(len(expected_tokens), len(candidate_tokens))
    if shorter_len and len(overlap) / shorter_len >= 0.6:
        return True

    expected_sides = _split_parties(expected)
    candidate_sides = _split_parties(candidate)
    if expected_sides and candidate_sides:
        left_overlap = _token_overlap_ratio(expected_sides[0], candidate_sides[0])
        right_overlap = _token_overlap_ratio(expected_sides[1], candidate_sides[1])
        if _has_party_conflict(expected_sides[0], candidate_sides[0]) or _has_party_conflict(
            expected_sides[1], candidate_sides[1]
        ):
            return False
        if left_overlap >= 0.5 and right_overlap >= 0.5:
            return True

    return False


def _normalize_case_name(value: str) -> str:
    normalized = value.casefold()
    normalized = re.sub(r",?\s+\d+\s+[a-z][a-z. ]+\s+\d+.*$", "", normalized)
    normalized = normalized.replace(" versus ", " v. ")
    normalized = re.sub(r"\bappellant/cross-appellee\b|\bappellee/cross-appellant\b", " ", normalized)
    normalized = re.sub(r"\bappellant\b|\bappellee\b|\bpetitioner\b|\brespondent\b", " ", normalized)
    replacements = {
        " corp. ": " corporation ",
        " corp ": " corporation ",
        " inc. ": " incorporated ",
        " inc ": " incorporated ",
        " co. ": " company ",
        " co ": " company ",
        " servs. ": " services ",
        " servs ": " services ",
        " svc. ": " service ",
        " svcs. ": " services ",
        " sys. ": " systems ",
        " sys ": " systems ",
        " envtl. ": " environmental ",
        " envtl ": " environmental ",
    }
    normalized = f" {normalized} "
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)
    normalized = re.sub(r"[\"'(),.;:/-]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _meaningful_tokens(value: str) -> set[str]:
    stopwords = {
        "v",
        "of",
        "the",
        "and",
        "a",
        "an",
        "incorporated",
        "corporation",
        "company",
        "limited",
        "llc",
        "ltd",
        "s",
        "n",
        "c",
        "city",
        "town",
        "county",
        "state",
    }
    return {token for token in value.split() if len(token) > 1 and token not in stopwords}


def _split_parties(value: str) -> tuple[set[str], set[str]] | None:
    if " v " not in value:
        return None
    left, right = value.split(" v ", 1)
    return _meaningful_tokens(left), _meaningful_tokens(right)


def _token_overlap_ratio(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def _has_party_conflict(left: set[str], right: set[str]) -> bool:
    if not left or not right:
        return False
    overlap = left & right
    if overlap:
        return False
    if len(left) == 1 and len(right) == 1:
        return True
    if min(len(left), len(right)) <= 2:
        return True
    return False


def _map_status(status_code: int | None, matched: bool) -> str:
    if matched:
        return "verified"
    if status_code == 300:
        return "ambiguous"
    if status_code == 404:
        return "not_found"
    if status_code == 429:
        return "rate_limited"
    if status_code == 400:
        return "invalid"
    return "rejected"


def _build_summary(status_code: int | None, matched: bool, candidate_count: int, error_message: str) -> str:
    if matched:
        return f"Matched at least one candidate exactly enough to verify the citation ({candidate_count} candidate result(s))."
    if status_code == 300:
        return f"The citation maps to multiple candidate cases ({candidate_count} results) and needs human review."
    if status_code == 404:
        return "The citation pattern looked valid, but no matching case was returned."
    if status_code == 429:
        return "The external service rate-limited this lookup."
    if status_code == 400:
        return error_message or "The citation text did not resolve to a valid reporter pattern."
    return error_message or "The citation matched a CourtListener record, but the case name or year in the document did not fully match."


def _check_id_references(citation: CitationRecord, matched: bool) -> None:
    base_page = _safe_int(citation.metadata.get("page"))
    pin_page = _safe_int(citation.metadata.get("pin_cite_page"))
    max_known_page = max(item for item in (base_page, pin_page) if item is not None) if any(
        item is not None for item in (base_page, pin_page)
    ) else None

    for ref in citation.id_references:
        if not ref.pin_cite_page:
            ref.status = "linked"
            ref.summary = "Linked to the preceding citation. No specific page was cited."
            continue
        if not matched:
            ref.status = "unverified"
            ref.summary = (
                f"Linked to the preceding citation and extracted page {ref.pin_cite_page}, "
                "but the parent citation was not verified against an external source."
            )
            continue

        requested_page = _safe_int(ref.pin_cite_page)
        if requested_page is None:
            ref.status = "unverified"
            ref.summary = "A page reference was detected, but it could not be parsed."
            continue
        if max_known_page is not None and requested_page < max_known_page:
            ref.status = "page_mismatch"
            ref.summary = (
                f"The Id. reference points to page {requested_page}, which is earlier than the parent citation's "
                f"known page reference ({max_known_page})."
            )
            continue

        ref.status = "page_plausible"
        ref.summary = (
            f"Linked to the preceding citation and extracted page {requested_page}. "
            "The current backend can structurally sanity-check the page number, but definitive reporter-page "
            "validation still requires a publisher database such as Westlaw or Lexis."
        )


def _safe_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
