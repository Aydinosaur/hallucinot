from __future__ import annotations

import json

from flask import Flask, jsonify, render_template, request

from hallucinot.config import get_courtlistener_token
from hallucinot.document_loader import extract_text
from hallucinot.extraction import extract_citations
from hallucinot.verification import build_verifier

app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html", courtlistener_configured=bool(get_courtlistener_token()))


@app.post("/analyze")
def analyze():
    uploaded = request.files.get("document")
    provider = request.form.get("provider", "Demo")
    if not uploaded or not uploaded.filename:
        return jsonify({"error": "Please upload a .pdf, .docx, or .txt file."}), 400

    try:
        text = extract_text(uploaded.filename, uploaded.read())
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Could not read the document: {exc}"}), 400

    if not text.strip():
        return jsonify({"error": "No readable text was found in the uploaded document."}), 400

    citations = extract_citations(text)
    if provider == "CourtListener" and not get_courtlistener_token():
        verifier = build_verifier(provider)
        if verifier.name != "CourtListener":
            return jsonify(
                {
                    "error": (
                        "CourtListener verification requires an API token. "
                        "Add COURTLISTENER_API_TOKEN to `/Users/ayden/claudeStuff/hallucinot/.env` "
                        "or set it in your shell before starting the app."
                    )
                }
            ), 400
    verifier = build_verifier(provider)
    try:
        verification_results = verifier.verify_all(citations, text)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Verification failed: {exc}"}), 502

    results = [_serialize_result(result) for result in verification_results]

    counts = {
        "characters": len(text),
        "citations_found": len(citations),
        "quoted_snippets": sum(1 for citation in citations if citation.quote_snippet),
        "id_references": sum(len(citation.id_references) for citation in citations),
        "verified": sum(1 for item in results if item["status"] == "verified"),
        "rejected": sum(1 for item in results if item["status"] == "rejected"),
        "ambiguous": sum(1 for item in results if item["status"] == "ambiguous"),
        "not_found": sum(1 for item in results if item["status"] == "not_found"),
    }

    return jsonify(
        {
            "provider": verifier.name,
            "summary": counts,
            "results": results,
            "report_json": json.dumps(results, indent=2),
        }
    )


def _serialize_result(result):
    return {
        "status": result.status,
        "citation": result.citation.normalized_text,
        "raw_text": result.citation.raw_text,
        "extracted_case_name": result.citation.extracted_case_name,
        "quote_snippet": result.citation.quote_snippet,
        "metadata": result.citation.metadata,
        "id_references": [
            {
                "raw_text": ref.raw_text,
                "pin_cite_text": ref.pin_cite_text,
                "pin_cite_page": ref.pin_cite_page,
                "status": ref.status,
                "summary": ref.summary,
            }
            for ref in result.citation.id_references
        ],
        "summary": result.summary,
        "checks": [
            {
                "field": check.field,
                "status": check.status,
                "expected": check.expected,
                "actual": check.actual,
                "summary": check.summary,
            }
            for check in result.checks
        ],
        "candidates": [
            {
                "case_name": candidate.case_name,
                "date_filed": candidate.date_filed,
                "court": candidate.court,
                "matched_citations": candidate.matched_citations,
                "url": candidate.url,
            }
            for candidate in result.candidates
        ],
    }


if __name__ == "__main__":
    app.run(debug=True)
