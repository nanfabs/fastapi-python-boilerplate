from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from lib.sanitizer import sanitize_geojson

app = FastAPI(title="GeoJSON Sanitizer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/sanitize")
async def sanitize(file: UploadFile = File(...)) -> JSONResponse:
    if not file.filename.lower().endswith((".json", ".geojson")):
        raise HTTPException(status_code=400, detail="Please upload a .json or .geojson file.")

    raw = await file.read()
    try:
        payload: Any = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Uploaded file is not valid UTF-8 JSON.") from exc

    try:
        result = sanitize_geojson(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return JSONResponse(result)
