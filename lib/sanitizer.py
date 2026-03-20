from __future__ import annotations

import copy
import math
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .aliases import (
    ALIASES,
    ALLOWED_FIELDS,
    DISTR_OPTIONS,
    PRACTICE_OPTIONS,
    TARGET_SYS_OPTIONS,
)

Fix = Dict[str, Any]


def sanitize_geojson(data: Any) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "summary": {
            "input_features": 0,
            "output_features": 0,
            "dropped_features": 0,
            "fixes_applied": 0,
        },
        "file_fixes": [],
        "feature_reports": [],
    }

    if not isinstance(data, dict):
        raise ValueError("Input must be a JSON object.")

    if data.get("type") != "FeatureCollection":
        report["file_fixes"].append(
            _fix("file", "set_type", "Top-level type was set to 'FeatureCollection'.")
        )

    features = data.get("features")
    if not isinstance(features, list):
        report["file_fixes"].append(
            _fix("file", "replace_features", "Top-level features was not a list; replaced with an empty list.")
        )
        features = []

    cleaned_features: List[Dict[str, Any]] = []
    report["summary"]["input_features"] = len(features)

    for index, feature in enumerate(features):
        cleaned, feature_report = sanitize_feature(feature, index)
        report["feature_reports"].append(feature_report)
        if cleaned is None:
            report["summary"]["dropped_features"] += 1
            continue
        cleaned_features.append(cleaned)

    sanitized = {
        "type": "FeatureCollection",
        "features": cleaned_features,
    }

    total_fixes = len(report["file_fixes"])
    for item in report["feature_reports"]:
        total_fixes += len(item.get("fixes", []))

    report["summary"]["output_features"] = len(cleaned_features)
    report["summary"]["fixes_applied"] = total_fixes
    return {"sanitized": sanitized, "report": report}


def sanitize_feature(feature: Any, index: int) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    feature_report: Dict[str, Any] = {
        "feature_index": index,
        "status": "kept",
        "fixes": [],
    }

    if not isinstance(feature, dict):
        feature_report["status"] = "dropped"
        feature_report["fixes"].append(
            _fix("feature", "drop", "Feature was not an object and was dropped.")
        )
        return None, feature_report

    if feature.get("type") != "Feature":
        feature_report["fixes"].append(
            _fix("feature", "set_type", "Feature type was normalized to 'Feature'.")
        )

    geometry, geometry_fixes = sanitize_geometry(feature.get("geometry"))
    feature_report["fixes"].extend(geometry_fixes)
    if geometry is None:
        feature_report["status"] = "dropped"
        feature_report["fixes"].append(
            _fix("feature", "drop", "Feature was dropped because geometry was invalid after sanitization.")
        )
        return None, feature_report

    properties, property_fixes = sanitize_properties(feature.get("properties"))
    feature_report["fixes"].extend(property_fixes)

    cleaned = {
        "type": "Feature",
        "geometry": geometry,
        "properties": properties,
    }
    return cleaned, feature_report


def sanitize_geometry(geometry: Any) -> Tuple[Optional[Dict[str, Any]], List[Fix]]:
    fixes: List[Fix] = []
    if not isinstance(geometry, dict):
        fixes.append(_fix("geometry", "invalid", "Geometry was missing or not an object."))
        return None, fixes

    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")

    if geometry_type == "Polygon":
        cleaned = sanitize_polygon(coordinates)
    elif geometry_type == "MultiPolygon":
        cleaned = sanitize_multipolygon(coordinates)
    else:
        fixes.append(
            _fix(
                "geometry",
                "unsupported_type",
                f"Unsupported geometry type '{geometry_type}'. Only Polygon and MultiPolygon are supported.",
            )
        )
        return None, fixes

    if cleaned is None:
        fixes.append(_fix("geometry", "invalid", "Geometry coordinates could not be repaired."))
        return None, fixes

    if _contains_z_values(coordinates):
        fixes.append(_fix("geometry", "strip_z", "Removed extra coordinate dimensions and kept only 2D coordinates."))

    if geometry_type == "Polygon" and _rings_were_auto_closed_polygon(coordinates, cleaned):
        fixes.append(_fix("geometry", "close_ring", "Auto-closed one or more polygon rings."))
    elif geometry_type == "MultiPolygon" and _rings_were_auto_closed_multipolygon(coordinates, cleaned):
        fixes.append(_fix("geometry", "close_ring", "Auto-closed one or more polygon rings."))

    return {"type": geometry_type, "coordinates": cleaned}, fixes


def sanitize_polygon(coords: Any) -> Optional[List[List[List[float]]]]:
    if not isinstance(coords, list) or not coords:
        return None

    cleaned_rings: List[List[List[float]]] = []
    for ring in coords:
        cleaned_ring = sanitize_ring(ring)
        if cleaned_ring is None:
            return None
        cleaned_rings.append(cleaned_ring)

    return cleaned_rings


def sanitize_multipolygon(coords: Any) -> Optional[List[List[List[List[float]]]]]:
    if not isinstance(coords, list) or not coords:
        return None

    cleaned_polygons: List[List[List[List[float]]]] = []
    for polygon in coords:
        cleaned_polygon = sanitize_polygon(polygon)
        if cleaned_polygon is None:
            return None
        cleaned_polygons.append(cleaned_polygon)
    return cleaned_polygons


def sanitize_ring(ring: Any) -> Optional[List[List[float]]]:
    if not isinstance(ring, list) or len(ring) < 3:
        return None

    cleaned_ring: List[List[float]] = []
    for point in ring:
        cleaned_point = sanitize_point(point)
        if cleaned_point is None:
            return None
        cleaned_ring.append(cleaned_point)

    if len(cleaned_ring) < 3:
        return None

    if cleaned_ring[0] != cleaned_ring[-1]:
        cleaned_ring.append(copy.deepcopy(cleaned_ring[0]))

    if len(cleaned_ring) < 4:
        return None

    return cleaned_ring


def sanitize_point(point: Any) -> Optional[List[float]]:
    if not isinstance(point, list) or len(point) < 2:
        return None

    lon = _coerce_number(point[0])
    lat = _coerce_number(point[1])
    if lon is None or lat is None:
        return None
    return [_round_coord(lon), _round_coord(lat)]


def sanitize_properties(properties: Any) -> Tuple[Dict[str, Any], List[Fix]]:
    fixes: List[Fix] = []
    source = properties if isinstance(properties, dict) else {}
    if not isinstance(properties, dict):
        fixes.append(_fix("properties", "replace", "Properties was missing or not an object; replaced with an empty object."))

    canonical: Dict[str, Any] = {}
    seen_canonical: set[str] = set()

    for key, value in source.items():
        normalized_key = normalize_property_name(key)
        if normalized_key != key:
            fixes.append(_fix("properties", "rename", f"Mapped property '{key}' to '{normalized_key}'."))

        if normalized_key not in ALLOWED_FIELDS:
            fixes.append(_fix("properties", "remove", f"Removed unsupported property '{key}'."))
            continue

        if normalized_key in seen_canonical:
            fixes.append(_fix("properties", "dedupe", f"Dropped duplicate property '{key}' after normalization."))
            continue

        canonical[normalized_key] = value
        seen_canonical.add(normalized_key)

    cleaned = {field: None for field in sorted(ALLOWED_FIELDS)}

    if "polyName" in canonical:
        cleaned["polyName"] = _sanitize_string(canonical["polyName"])
        if canonical["polyName"] is not None and cleaned["polyName"] is None:
            fixes.append(_fix("properties", "nullify", "Set invalid polyName to null."))

    if "plantStart" in canonical:
        cleaned["plantStart"] = _sanitize_date(canonical["plantStart"])
        if canonical["plantStart"] not in (None, "") and cleaned["plantStart"] is None:
            fixes.append(_fix("properties", "nullify", "Set invalid plantStart to null."))

    if "practice" in canonical:
        value, changed = _sanitize_enum_field(canonical["practice"], PRACTICE_OPTIONS)
        cleaned["practice"] = value
        if changed:
            fixes.append(_fix("properties", "normalize", "Normalized practice and set invalid values to null."))

    if "targetSys" in canonical:
        value = _sanitize_enum_scalar(canonical["targetSys"], TARGET_SYS_OPTIONS)
        cleaned["targetSys"] = value
        if canonical["targetSys"] not in (None, value):
            if value is None:
                fixes.append(_fix("properties", "nullify", "Set invalid targetSys to null."))
            else:
                fixes.append(_fix("properties", "normalize", "Normalized targetSys."))

    if "distr" in canonical:
        value, changed = _sanitize_enum_field(canonical["distr"], DISTR_OPTIONS)
        cleaned["distr"] = value
        if changed:
            fixes.append(_fix("properties", "normalize", "Normalized distr and set invalid values to null."))

    if "numTrees" in canonical:
        value = _sanitize_num_trees(canonical["numTrees"])
        cleaned["numTrees"] = value
        if canonical["numTrees"] not in (None, "", value):
            if value is None:
                fixes.append(_fix("properties", "nullify", "Set invalid numTrees to null."))
            else:
                fixes.append(_fix("properties", "normalize", "Normalized numTrees."))

    if "siteId" in canonical:
        cleaned["siteId"] = _sanitize_site_id(canonical["siteId"])
        if canonical["siteId"] not in (None, cleaned["siteId"]):
            if cleaned["siteId"] is None:
                fixes.append(_fix("properties", "nullify", "Set invalid siteId to null."))
            else:
                fixes.append(_fix("properties", "normalize", "Normalized siteId."))

    return cleaned, fixes


def normalize_property_name(name: str) -> str:
    if name in ALLOWED_FIELDS:
        return name
    lowered = str(name).strip()
    slug = re.sub(r"[^A-Za-z0-9]+", "_", lowered).strip("_")
    compact = re.sub(r"[^A-Za-z0-9]+", "", lowered)
    return (
        ALIASES.get(name)
        or ALIASES.get(lowered)
        or ALIASES.get(slug)
        or ALIASES.get(compact.lower())
        or name
    )


def _sanitize_enum_field(value: Any, allowed: set[str]) -> Tuple[Optional[Any], bool]:
    if value is None or value == "":
        return None, value not in (None,)

    if isinstance(value, list):
        cleaned_list: List[str] = []
        changed = False
        for item in value:
            normalized = _sanitize_enum_scalar(item, allowed)
            if normalized is None:
                changed = True
                continue
            cleaned_list.append(normalized)
        cleaned_list = list(dict.fromkeys(cleaned_list))
        if not cleaned_list:
            return None, True
        if len(cleaned_list) == 1:
            return cleaned_list[0], True
        return cleaned_list, changed

    normalized = _sanitize_enum_scalar(value, allowed)
    if normalized is None:
        return None, True
    return normalized, normalized != value


def _sanitize_enum_scalar(value: Any, allowed: set[str]) -> Optional[str]:
    if value is None:
        return None
    text = _sanitize_string(value)
    if text is None:
        return None
    if text in allowed:
        return text
    return None


def _sanitize_num_trees(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    number = _coerce_number(value)
    if number is None:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return int(number) if float(number).is_integer() else round(number, 2)


def _sanitize_site_id(value: Any) -> Optional[str]:
    text = _sanitize_string(value)
    return text


def _sanitize_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        text = str(value)
    else:
        return None
    return text or None


def _sanitize_date(value: Any) -> Optional[str]:
    text = _sanitize_string(value)
    if text is None:
        return None
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return text
    except ValueError:
        return None


def _coerce_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _round_coord(value: float) -> float:
    return round(float(value), 9)


def _contains_z_values(coords: Any) -> bool:
    if isinstance(coords, list):
        if len(coords) >= 3 and all(not isinstance(item, list) for item in coords[:3]):
            return True
        return any(_contains_z_values(item) for item in coords)
    return False


def _rings_were_auto_closed_polygon(original: Any, cleaned: Any) -> bool:
    if not isinstance(original, list) or not isinstance(cleaned, list):
        return False
    for original_ring, cleaned_ring in zip(original, cleaned):
        if _ring_was_auto_closed(original_ring, cleaned_ring):
            return True
    return False


def _rings_were_auto_closed_multipolygon(original: Any, cleaned: Any) -> bool:
    if not isinstance(original, list) or not isinstance(cleaned, list):
        return False
    for original_polygon, cleaned_polygon in zip(original, cleaned):
        if _rings_were_auto_closed_polygon(original_polygon, cleaned_polygon):
            return True
    return False


def _ring_was_auto_closed(original_ring: Any, cleaned_ring: Any) -> bool:
    if not isinstance(original_ring, list) or not original_ring:
        return False
    if not isinstance(cleaned_ring, list) or not cleaned_ring:
        return False
    original_first = sanitize_point(original_ring[0]) if isinstance(original_ring[0], list) else None
    original_last = sanitize_point(original_ring[-1]) if isinstance(original_ring[-1], list) else None
    return original_first is not None and original_last is not None and original_first != original_last and cleaned_ring[0] == cleaned_ring[-1]


def _fix(scope: str, code: str, message: str) -> Fix:
    return {"scope": scope, "code": code, "message": message}
