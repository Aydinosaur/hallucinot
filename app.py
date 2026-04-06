from __future__ import annotations

import json
import os
import time
from collections import defaultdict, deque

from flask import Flask, jsonify, request

from hallucinot.config import get_courtlistener_token
from hallucinot.document_loader import extract_document
from hallucinot.extraction import extract_citations
from hallucinot.verification import build_verifier


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "15")) * 1024 * 1024
    rate_limit_window = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "300"))
    rate_limit_max = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "20"))
    request_log: defaultdict[str, deque[float]] = defaultdict(deque)

    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get("Origin", "")
        allowed_origin = os.getenv("ALLOWED_ORIGIN", "*").strip() or "*"
        if allowed_origin == "*" or origin == allowed_origin:
            response.headers["Access-Control-Allow-Origin"] = "*" if allowed_origin == "*" else origin
            response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        return response

    @app.route("/api/analyze", methods=["POST", "OPTIONS"])
    def analyze():
        if request.method == "OPTIONS":
            return ("", 204)

        client_ip = _client_ip()
        allowed, retry_after = _check_rate_limit(request_log, client_ip, rate_limit_window, rate_limit_max)
        if not allowed:
            response = jsonify(
                {
                    "error": (
                        f"Rate limit exceeded. Please wait about {retry_after} seconds before uploading another document."
                    )
                }
            )
            response.status_code = 429
            response.headers["Retry-After"] = str(retry_after)
            return response

        uploaded = request.files.get("document")
        provider = request.form.get("provider", "CourtListener")
        if not uploaded or not uploaded.filename:
            return jsonify({"error": "Please upload a .docx file."}), 400
        if not uploaded.filename.lower().endswith(".docx"):
            return jsonify({"error": "Only .docx files are supported right now."}), 400

        try:
            loaded_document = extract_document(uploaded.filename, uploaded.read())
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": f"Could not read the document: {exc}"}), 400

        text = loaded_document.text
        if not text.strip():
            return jsonify({"error": "No readable text was found in the uploaded document."}), 400

        citations = extract_citations(text, styled_ranges=loaded_document.styled_ranges)
        if provider == "CourtListener" and not get_courtlistener_token():
            verifier = build_verifier(provider)
            if verifier.name != "CourtListener":
                return jsonify(
                    {
                        "error": (
                            "CourtListener verification requires an API token. "
                            "Set COURTLISTENER_API_TOKEN in your backend environment before deploying."
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

    @app.get("/api/health")
    def health():
        return jsonify(
            {
                "ok": True,
                "service": "hallucinot-api",
                "courtlistenerConfigured": bool(get_courtlistener_token()),
                "rateLimitWindowSeconds": rate_limit_window,
                "rateLimitMaxRequests": rate_limit_max,
            }
        )

    @app.get("/")
    def root():
        return jsonify(
            {
                "service": "hallucinot-api",
                "message": "HalluciNot backend is running. Deploy the static frontend separately on Netlify.",
                "analyzeEndpoint": "/api/analyze",
                "healthEndpoint": "/api/health",
            }
        )

    return app


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


def _client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _check_rate_limit(
    request_log: defaultdict[str, deque[float]],
    client_ip: str,
    window_seconds: int,
    max_requests: int,
) -> tuple[bool, int]:
    now = time.time()
    timestamps = request_log[client_ip]
    while timestamps and now - timestamps[0] > window_seconds:
        timestamps.popleft()
    if len(timestamps) >= max_requests:
        retry_after = max(1, int(window_seconds - (now - timestamps[0])))
        return False, retry_after
    timestamps.append(now)
    return True, 0


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
