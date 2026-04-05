# HalluciNot

HalluciNot is a simple local app for checking whether legal citations in a document appear to correspond to real cases.

It currently supports:

- Drag-and-drop upload for `.pdf`, `.docx`, and `.txt`
- Citation extraction using `eyecite`
- Quote-snippet detection near citations
- Verification through:
  - `CourtListener` as the primary live verification backend
  - a local demo mode when no API credentials are available
- A human-readable report in the browser

## Why CourtListener for the MVP

Lexis and Westlaw both provide document-upload citation checking features in their products, but their public developer access is limited or unclear for a self-serve app. This MVP uses CourtListener because it offers a documented citation lookup API that is suitable for prototyping and early validation.

The code is organized so a Westlaw or Lexis integration can be added later as another verifier backend if you obtain enterprise access.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python app.py
```

## Deploy on the web

This repo now supports a split deployment:

- Netlify for the frontend in [`frontend/`](/Users/ayden/claudeStuff/hallucinot/frontend)
- Cloud Run for the Python API in [`app.py`](/Users/ayden/claudeStuff/hallucinot/app.py)

Deployment files included:

- [`requirements.txt`](/Users/ayden/claudeStuff/hallucinot/requirements.txt)
- [`Dockerfile`](/Users/ayden/claudeStuff/hallucinot/Dockerfile)
- [`netlify.toml`](/Users/ayden/claudeStuff/hallucinot/netlify.toml)
- [`render.yaml`](/Users/ayden/claudeStuff/hallucinot/render.yaml)
- [`DEPLOY.md`](/Users/ayden/claudeStuff/hallucinot/DEPLOY.md)

## CourtListener setup

The app now reads the CourtListener token on the server side automatically. The browser never needs to know the key.

You can configure it in either of two ways:

1. Set an environment variable before starting the app:

```bash
export COURTLISTENER_API_TOKEN="your-token"
```

2. Or create `/Users/ayden/claudeStuff/hallucinot/.env` with:

```bash
COURTLISTENER_API_TOKEN="your-token"
```

The app uses CourtListener's official bulk citation lookup API as its primary verifier. This is more efficient than checking citations one at a time and better fits CourtListener's documented throttles.

If you choose `Demo`, the app still extracts citations without running live verification.

## Current limits

- Scanned PDFs are not OCR'd yet. PDFs must contain selectable text.
- Quote checking is limited to extracting nearby quoted snippets for review. It does not yet validate quote text against the source opinion.
- CourtListener does not look up statutes, law reviews, `id.`, or `supra` directly. The app handles `Id.` locally by attaching it to the previous citation.
- CourtListener limits citation lookup requests to 250 citations per request and documents throttles for high-volume usage.
- CourtListener does not cover every proprietary reporter workflow that Lexis or Westlaw may support.
