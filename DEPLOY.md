# Deploy HalluciNot

HalluciNot is now prepared for:

- **Frontend**: Netlify
- **Backend**: Google Cloud Run

## 1. Deploy the backend to Cloud Run

From `/Users/ayden/claudeStuff/hallucinot`:

```bash
gcloud run deploy hallucinot-api \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars COURTLISTENER_API_TOKEN=your-token-here
```

Optional CORS restriction:

```bash
gcloud run services update hallucinot-api \
  --region us-central1 \
  --update-env-vars ALLOWED_ORIGIN=https://your-netlify-site.netlify.app
```

The API routes are:

- `GET /api/health`
- `POST /api/analyze`

## 2. Configure the frontend for Netlify

Edit [`frontend/config.js`](/Users/ayden/claudeStuff/hallucinot/frontend/config.js):

```js
window.HALLUCINOT_CONFIG = {
  API_BASE_URL: "https://your-cloud-run-service-url.a.run.app",
};
```

## 3. Deploy the frontend to Netlify

This repo already includes [`netlify.toml`](/Users/ayden/claudeStuff/hallucinot/netlify.toml), which publishes the `frontend/` folder.

On Netlify:

1. Create a new site from Git
2. Select this repo
3. Netlify should detect:
   - publish directory: `frontend`
4. Deploy

## 4. Recommended next hardening steps

- Restrict `ALLOWED_ORIGIN` to your real Netlify domain
- Add upload size limits in Cloud Run settings if needed
- Privacy and Terms pages now live in `frontend/privacy.html` and `frontend/terms.html`
- Tune `RATE_LIMIT_MAX_REQUESTS` and `RATE_LIMIT_WINDOW_SECONDS` for your traffic level
- Replace the placeholder value in [`frontend/config.js`](/Users/ayden/claudeStuff/hallucinot/frontend/config.js) before publishing

## Notes

- The backend keeps the CourtListener token server-side.
- The frontend is fully static and can be cached and served quickly by Netlify.
- Local Flask templates remain in the repo for design continuity, but the deployed frontend should come from `frontend/`.
