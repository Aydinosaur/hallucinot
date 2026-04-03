# Deploy HalluciNot

## Fastest option: Render

This repo is ready for Render with [`render.yaml`](/Users/ayden/claudeStuff/hallucinot/render.yaml).

### 1. Push this folder to GitHub

If this is not already a Git repo:

```bash
cd /Users/ayden/claudeStuff/hallucinot
git init
git add .
git commit -m "Prepare HalluciNot for deployment"
```

Then create a GitHub repo and push:

```bash
git remote add origin <your-github-repo-url>
git branch -M main
git push -u origin main
```

### 2. Create the Render service

1. Log in to [Render](https://render.com/)
2. Click `New +`
3. Choose `Blueprint`
4. Select your GitHub repo
5. Render will detect [`render.yaml`](/Users/ayden/claudeStuff/hallucinot/render.yaml)

### 3. Add your secret

In Render, set:

```txt
COURTLISTENER_API_TOKEN=your-token-here
```

### 4. Deploy

Render will build with:

```bash
pip install -r requirements.txt
```

and start with:

```bash
gunicorn app:app
```

## Notes

- The Flask app is fine behind `gunicorn`; you do not need to run `python app.py` in production.
- Keep the CourtListener token only in Render environment variables, not in the repo.
- The free tier may sleep after inactivity depending on Render's current policy.
