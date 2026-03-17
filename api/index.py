from fastapi import FastAPI, UploadFile, File
import json

app = FastAPI()

# Add this! It helps you verify the API is actually "awake"
@app.get("/api")
async def health_check():
    return {"status": "TerraMatch Sanitizer is Online"}

# Your existing sanitize code follows...

def clean_coordinates(coords):
    if isinstance(coords, (list, tuple)):
        if len(coords) >= 2 and isinstance(coords[0], (int, float)):
            return [round(float(coords[0]), 10), round(float(coords[1]), 10)]
        return [clean_coordinates(c) for c in coords]
    return coords

@app.post("/api/sanitize")
async def sanitize_geojson(file: UploadFile = File(...), site_id: str = "3558"):
    # Read the uploaded file
    content = await file.read()
    data = json.loads(content)
    
    new_features = []
    for feat in data.get("features", []):
        old_props = feat.get("properties", {})
        
        # Mapping logic
        new_props = {
            "polyName": old_props.get("polyName") or old_props.get("Name") or "Unnamed",
            "plantStart": old_props.get("plantStart") or "2024-01-01",
            "practice": [old_props.get("practice").lower()] if old_props.get("practice") else None,
            "targetSys": old_props.get("targetSys"),
            "distr": [old_props.get("distr").lower()] if old_props.get("distr") else None,
            "numTrees": old_props.get("numTrees", 0),
            "siteId": site_id
        }

        new_features.append({
            "type": "Feature",
            "geometry": {
                "type": feat["geometry"]["type"],
                "coordinates": clean_coordinates(feat["geometry"]["coordinates"])
            },
            "properties": new_props
        })

    return {"type": "FeatureCollection", "features": new_features}
