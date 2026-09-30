"""'Sensor placement' report section from a revision's annotations.json.

The section appears only when the revision carries sensor markers. HTML gets
the original photograph with absolutely positioned, keyboard-focusable marker
buttons whose pixel positions report.js derives from normalized coordinates
at display time; the PDF gets a static SVG overlay generated here. The image
is copied into the report folder by hash and the copy is verified. Every
caption, sensor identifier and label is escaped; nothing from the annotation
file is emitted as markup. A hash mismatch is an error, never a silent skip.
"""
from __future__ import annotations

import base64
import hashlib
import html
from pathlib import Path
from typing import Callable

from ..annotations import load_annotations
from ..attachments import AssetStore

# The appendix traceability line of renderer._body(); the section is inserted before it.
FOOTER_MARKER = "**Traceability:** "
SVG_NAME = "sensor-placement.svg"


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def sensor_placement_html(annotations: dict, asset: dict, image_src: str) -> str:
    """Self-positioning figure markup; percentages are the no-script fallback."""
    width, height = asset.get("width"), asset.get("height")
    digest = annotations["image_asset_sha256"]
    markers = annotations["markers"]
    name = asset.get("original_name") or f"{digest[:16]}…"
    caption = asset.get("caption") or ""
    alt = f"Photograph {name} with {len(markers)} documented sensor location(s)"
    size = f' width="{int(width)}" height="{int(height)}"' if isinstance(width, int) and isinstance(height, int) else ""
    out = [f'<div class="sensor-placement-block" data-image-sha256="{_escape(digest)}">',
           '<figure class="sensor-placement">', '<div class="sensor-image-frame">',
           f'<img class="sensor-image" src="{_escape(image_src)}"{size} alt="{_escape(alt)}" decoding="async">']
    for index, marker in enumerate(markers, 1):
        x, y = marker["x_norm"], marker["y_norm"]
        description = f"Sensor {index}: {marker['sensor_id']}. {marker['label']}".strip()
        out.append(f'<button type="button" class="sensor-marker" data-x-norm="{x:.6f}" data-y-norm="{y:.6f}" '
                   f'data-sensor-id="{_escape(marker["sensor_id"])}" style="left:{x * 100:.4f}%;top:{y * 100:.4f}%" '
                   f'aria-pressed="false" aria-label="{_escape(description)}" title="{_escape(description)}">{index}'
                   f'<span class="sensor-marker-label" aria-hidden="true">{_escape(marker["sensor_id"])}</span></button>')
    out.append("</div>")
    out.append(f'<figcaption>{_escape(caption) + " " if caption else ""}Sensor markers use normalized image coordinates '
               f'bound to original image SHA-256 {_escape(digest)}. They document attachment locations; '
               f'no temperature field is inferred between them.</figcaption></figure>')
    out.append('<p class="sensor-marker-detail" aria-live="polite">Select a marker (click, or Tab and Enter) to read its sensor identifier and location note.</p>')
    out.append('<table class="sensor-marker-table"><caption>Documented sensor markers</caption><thead><tr>'
               '<th scope="col">#</th><th scope="col">Sensor</th><th scope="col">Location note</th>'
               '<th scope="col">x (normalized)</th><th scope="col">y (normalized)</th></tr></thead><tbody>')
    for index, marker in enumerate(markers, 1):
        out.append(f'<tr data-sensor-id="{_escape(marker["sensor_id"])}"><th scope="row">{index}</th>'
                   f'<td>{_escape(marker["sensor_id"])}</td><td>{_escape(marker["label"]) or "—"}</td>'
                   f'<td>{marker["x_norm"]:.4f}</td><td>{marker["y_norm"]:.4f}</td></tr>')
    out.append("</tbody></table></div>")
    return "\n".join(out)


def static_overlay_svg(image: bytes, asset: dict, annotations: dict) -> str:
    """Photograph plus markers as one SVG for the print document."""
    width, height = asset.get("width"), asset.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise ValueError("Sensor placement image needs known pixel dimensions")
    uri = f"data:{asset['media_type']};base64,{base64.b64encode(image).decode('ascii')}"
    radius = max(6.0, min(width, height) * 0.012)
    font = max(11.0, min(width, height) * 0.02)
    name = asset.get("original_name") or annotations["image_asset_sha256"][:16]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           f'width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" '
           f'aria-label="{_escape("Sensor placement on " + str(name))}">',
           f'<title>{_escape("Sensor placement on " + str(name))}</title>',
           f'<image href="{uri}" xlink:href="{uri}" x="0" y="0" width="{width}" height="{height}"/>']
    for index, marker in enumerate(annotations["markers"], 1):
        cx, cy = marker["x_norm"] * width, marker["y_norm"] * height
        anchor, dx = ("end", -radius * 1.6) if marker["x_norm"] > 0.75 else ("start", radius * 1.6)
        out.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{radius:.2f}" fill="#D55E00" stroke="#FFFFFF" '
                   f'stroke-width="{radius / 4:.2f}"/>')
        out.append(f'<text x="{cx:.2f}" y="{cy + font * 0.3:.2f}" font-size="{font * 0.8:.1f}" text-anchor="middle" '
                   f'font-family="DejaVu Sans, Liberation Sans, sans-serif" font-weight="700" fill="#FFFFFF">{index}</text>')
        out.append(f'<text x="{cx + dx:.2f}" y="{cy + font * 0.35:.2f}" font-size="{font:.1f}" text-anchor="{anchor}" '
                   f'font-family="DejaVu Sans, Liberation Sans, sans-serif" font-weight="600" fill="#183047" '
                   f'stroke="#FFFFFF" stroke-width="{font * 0.25:.2f}" paint-order="stroke">'
                   f'{_escape(marker["sensor_id"])}</text>')
    out.append("</svg>")
    return "\n".join(out)


def sensor_placement_markdown(annotations: dict, asset: dict, image_src: str, svg_src: str,
                              markdown_escape: Callable[[object], str]) -> str:
    digest = annotations["image_asset_sha256"]
    name = asset.get("original_name") or "the stored original"
    caption = asset.get("caption") or ""
    rows = ["| # | Sensor | Location note | x | y |", "|---|---|---|---|---|"]
    for index, marker in enumerate(annotations["markers"], 1):
        rows.append(f"| {index} | {markdown_escape(marker['sensor_id'])} | {markdown_escape(marker['label']) or '—'} | "
                    f"{marker['x_norm']:.4f} | {marker['y_norm']:.4f} |")
    print_caption = (markdown_escape(caption) + " " if caption else "") + \
        "Sensor markers on the original photograph; positions are normalized image coordinates."
    return "\n".join([
        "## Sensor placement {#sensor-placement}", "",
        f"Documented sensor locations on photograph {markdown_escape(name)} (SHA-256 {digest}). "
        "Marker positions are normalized image coordinates bound to that exact image hash, so a resized view keeps "
        "each marker on the same physical location. They record where sensors were attached; they are not "
        "temperature values and no continuous temperature field is inferred.", "",
        '::: {.content-visible when-format="html"}', "```{=html}",
        sensor_placement_html(annotations, asset, image_src), "```", ":::", "",
        '::: {.content-visible unless-format="html"}', "",
        f"![{print_caption}]({svg_src})", "", *rows, "", ":::", ""])


def with_sensor_placement(body: str, out_dir: Path, markdown_escape: Callable[[object], str]) -> str:
    """Insert the section before the report footer when this revision has markers.

    Copies the verified original into ``assets/`` and writes the print SVG.
    Raises when the referenced original is missing or its hash differs.
    """
    out_dir = Path(out_dir)
    loaded = load_annotations(out_dir)
    if loaded is None:
        return body
    annotations, asset = loaded
    store = AssetStore(out_dir.parent.parent)
    image, asset = store.read(annotations["image_asset_sha256"])
    assets_dir = out_dir / "assets"
    assets_dir.mkdir(exist_ok=True)
    copy = assets_dir / store.path_for(asset).name
    copy.write_bytes(image)
    if hashlib.sha256(copy.read_bytes()).hexdigest() != annotations["image_asset_sha256"]:
        raise ValueError("Copied sensor placement image does not match its recorded hash")
    figures = out_dir / "figures"
    figures.mkdir(exist_ok=True)
    (figures / SVG_NAME).write_text(static_overlay_svg(image, asset, annotations), encoding="utf-8")
    section = sensor_placement_markdown(annotations, asset, f"assets/{copy.name}", f"figures/{SVG_NAME}", markdown_escape)
    lines = body.split("\n")
    index = next((i for i, line in enumerate(lines) if line.startswith(FOOTER_MARKER)), None)
    if index is None:
        return body.rstrip("\n") + "\n\n" + section
    return "\n".join(lines[:index]) + "\n" + section + "\n" + "\n".join(lines[index:])
