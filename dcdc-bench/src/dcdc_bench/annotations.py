"""Sensor placement annotations bound to an exact original image hash.

``reports/<revision>/annotations.json`` with markers has exactly this shape::

    {"schema_version": "1.0", "image_asset_sha256": "<hex>",
     "markers": [{"sensor_id": "...", "x_norm": 0.0-1.0, "y_norm": 0.0-1.0, "label": "..."}]}

Coordinates are normalized to the original image, so a resized rendering keeps
each marker on the same physical location (brief 10). Loading refuses an image
whose stored bytes no longer hash to ``image_asset_sha256`` (WEB-11). Saving
annotations always creates a new report revision; acquisition files are never
modified. This module also holds the editor's pure geometry helpers so the
NiceGUI page stays thin and testable without a browser.
"""
from __future__ import annotations

import html
import json
import math
import re
from pathlib import Path
from typing import Any

from .attachments import IMAGE_TYPES, AssetStore

SCHEMA_VERSION = "1.0"
ANNOTATION_KEYS = frozenset({"schema_version", "image_asset_sha256", "markers"})
MARKER_KEYS = frozenset({"sensor_id", "x_norm", "y_norm", "label"})
MAX_MARKERS = 200
MAX_LABEL = 200
SENSOR_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
HASH = re.compile(r"[0-9a-f]{64}")
PLACEHOLDER = {"schema_version": "1.0", "author_interpretation": [], "assets": []}
NUDGE = 0.005
NUDGE_LARGE = 0.02
HIT_RADIUS = 0.02


class AnnotationError(ValueError):
    """The annotation document does not follow the sensor placement schema."""


def _coordinate(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise AnnotationError(f"Marker {name} must be a finite number")
    if not 0.0 <= value <= 1.0:
        raise AnnotationError(f"Marker {name} must lie within the image (0 to 1)")
    return float(value)


def validate_marker(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) != MARKER_KEYS:
        raise AnnotationError("Each marker needs exactly sensor_id, x_norm, y_norm and label")
    sensor_id = value["sensor_id"]
    if not isinstance(sensor_id, str) or not SENSOR_ID.fullmatch(sensor_id):
        raise AnnotationError("sensor_id must be a short identifier (letters, digits, _ . : -)")
    label = value["label"]
    if not isinstance(label, str) or len(label) > MAX_LABEL:
        raise AnnotationError(f"Marker label must be text of at most {MAX_LABEL} characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in label):
        raise AnnotationError("Marker label contains control characters")
    return {"sensor_id": sensor_id, "x_norm": _coordinate(value["x_norm"], "x_norm"),
            "y_norm": _coordinate(value["y_norm"], "y_norm"), "label": label}


def validate_annotations(value: Any) -> dict:
    """Return a normalized copy in the exact schema, or raise AnnotationError."""
    if not isinstance(value, dict) or set(value) != ANNOTATION_KEYS:
        raise AnnotationError("Annotations need exactly schema_version, image_asset_sha256 and markers")
    if value["schema_version"] != SCHEMA_VERSION:
        raise AnnotationError(f"Unsupported annotations schema_version {value['schema_version']!r}")
    digest = value["image_asset_sha256"]
    if not isinstance(digest, str) or not HASH.fullmatch(digest):
        raise AnnotationError("image_asset_sha256 must be 64 lowercase hex characters")
    markers = value["markers"]
    if not isinstance(markers, list) or len(markers) > MAX_MARKERS:
        raise AnnotationError(f"markers must be a list of at most {MAX_MARKERS} entries")
    normalized = [validate_marker(marker) for marker in markers]
    ids = [marker["sensor_id"] for marker in normalized]
    if len(set(ids)) != len(ids):
        raise AnnotationError("sensor_id values must be unique within one image")
    return {"schema_version": SCHEMA_VERSION, "image_asset_sha256": digest, "markers": normalized}


def annotation_document(image_sha256: str, markers: list[dict]) -> dict:
    """Build the exact on-disk document from editor state."""
    return validate_annotations({"schema_version": SCHEMA_VERSION, "image_asset_sha256": image_sha256,
                                 "markers": [{key: marker[key] for key in MARKER_KEYS} for marker in markers]})


def has_markers(value: Any) -> bool:
    return isinstance(value, dict) and "markers" in value and "image_asset_sha256" in value


def bind_annotations(run_dir: Path, value: Any) -> tuple[dict, dict]:
    """Validate the schema and prove the referenced original exists with that hash."""
    annotations = validate_annotations(value)
    _, asset = AssetStore(run_dir).resolve(annotations["image_asset_sha256"])
    if asset.get("media_type") not in IMAGE_TYPES:
        raise AnnotationError("Sensor markers need a PNG, JPEG or SVG photograph, not a document")
    return annotations, asset


def annotations_file(run_dir: Path, value: Any | None) -> dict:
    """Content for a new revision's annotations.json: bound markers or the empty placeholder."""
    if value is None:
        return dict(PLACEHOLDER)
    annotations, _ = bind_annotations(run_dir, value)
    return annotations


def load_annotations(report_dir: Path, run_dir: Path | None = None) -> tuple[dict, dict] | None:
    """Read a revision's annotations; None when it carries no sensor markers.

    Raises AssetNotFound or AssetHashMismatch when the referenced original is
    absent or its current bytes hash differently from the saved reference.
    """
    report_dir = Path(report_dir)
    path = report_dir / "annotations.json"
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not has_markers(value):
        return None
    return bind_annotations(Path(run_dir) if run_dir is not None else report_dir.parent.parent, value)


# --- editor geometry; no GUI, filesystem or hardware ------------------------

def clamp(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def normalized_point(x_px: float, y_px: float, width: int, height: int) -> tuple[float, float]:
    """Image pixel coordinates to normalized coordinates, clamped inside the image."""
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise AnnotationError("Image dimensions are unknown; markers cannot be normalized")
    return clamp(x_px / width), clamp(y_px / height)


def nudge_marker(marker: dict, key: str, *, large: bool = False) -> dict:
    """Return a moved copy for an arrow key name; other keys return the marker unchanged."""
    step = NUDGE_LARGE if large else NUDGE
    deltas = {"ArrowLeft": (-step, 0.0), "ArrowRight": (step, 0.0), "ArrowUp": (0.0, -step), "ArrowDown": (0.0, step)}
    if key not in deltas:
        return dict(marker)
    dx, dy = deltas[key]
    return {**marker, "x_norm": round(clamp(marker["x_norm"] + dx), 6), "y_norm": round(clamp(marker["y_norm"] + dy), 6)}


def nearest_marker(markers: list[dict], x_norm: float, y_norm: float, radius: float = HIT_RADIUS) -> int | None:
    best, distance = None, radius
    for index, marker in enumerate(markers):
        separation = math.hypot(marker["x_norm"] - x_norm, marker["y_norm"] - y_norm)
        if separation <= distance:
            best, distance = index, separation
    return best


def new_sensor_id(markers: list[dict]) -> str:
    taken = {marker["sensor_id"] for marker in markers}
    number = len(markers) + 1
    while f"S{number}" in taken:
        number += 1
    return f"S{number}"


def marker_overlay_svg(markers: list[dict], width: int, height: int, selected: int | None = None) -> str:
    """SVG overlay for the editor image; every label is escaped, nothing is interactive."""
    radius = max(6.0, min(width, height) * 0.012)
    font = max(11.0, min(width, height) * 0.02)
    parts = []
    for index, marker in enumerate(markers):
        cx, cy = marker["x_norm"] * width, marker["y_norm"] * height
        fill = "#15608f" if index == selected else "#d55e00"
        stroke = radius / 3 if index == selected else radius / 4
        text = html.escape(f"{index + 1} {marker['sensor_id']}", quote=True)
        anchor, dx = ("end", -radius * 1.6) if marker["x_norm"] > 0.75 else ("start", radius * 1.6)
        parts.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{radius:.2f}" fill="{fill}" stroke="#ffffff" '
                     f'stroke-width="{stroke:.2f}" pointer-events="none"/>')
        parts.append(f'<text x="{cx + dx:.2f}" y="{cy + font * 0.35:.2f}" font-size="{font:.1f}" font-family="system-ui, sans-serif" '
                     f'font-weight="600" fill="#183047" stroke="#ffffff" stroke-width="{font * 0.25:.2f}" '
                     f'paint-order="stroke" text-anchor="{anchor}" pointer-events="none">{text}</text>')
    return "".join(parts)
