# GeoJSON Sanitizer

A small Vercel-ready app for sanitizing user-uploaded GeoJSON files before they reach TM.

## What it does

- keeps only `Polygon` and `MultiPolygon`
- strips 3D coordinates down to 2D
- auto-closes polygon rings when needed
- removes unsupported properties
- auto-maps common bad property names
- validates `practice`, `targetSys`, and `distr`
- sets invalid field values to `null`
- drops features with unrecoverable geometry

## Project structure

- `api/sanitize.py` - FastAPI endpoint for upload + sanitization
- `lib/sanitizer.py` - sanitizer logic
- `lib/aliases.py` - allowed fields, aliases, enums
- `public/index.html` - simple upload UI

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt uvicorn
uvicorn api.sanitize:app --reload
```

Then open `http://127.0.0.1:8000/public/index.html`.

## Deploy on Vercel

1. Push this folder to GitHub.
2. Import the repo into Vercel.
3. Vercel will install `requirements.txt` and expose the FastAPI route under `/api/sanitize`.

## Notes

The current implementation treats all known fields as optional and initializes missing fields to `null` in the output.
