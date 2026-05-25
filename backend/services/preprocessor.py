"""
═══════════════════════════════════════════════════════════════════════════════
PROCESS FORGE — Image Pre-Processor
═══════════════════════════════════════════════════════════════════════════════

Enterprise process diagrams are often very tall — 3,000 to 5,000px — covering
20 swimlanes and 50+ steps. Sending an image that large to a vision API risks
losing detail in small text and thin sequence arrows.

This module solves that with automatic tiling:

  1. DETECT  — needs_tiling() checks height and pixel-level readability score
  2. SPLIT   — tile_image() cuts the image into 700px vertical sections
  3. OVERLAP — each tile overlaps the next by 18% (≈126px) so no step or
               arrow is cut off exactly at a tile boundary
  4. ENHANCE — each tile gets contrast ×1.4, sharpness ×1.8, brightness ×1.05
               making small labels easier for Claude Vision to read

All tiles are passed to claude_service.py which sends them to Claude in a
SINGLE API call with positional context ("Tile 2 of 4, rows 574–1274px,
overlaps 126px with Tile 1"). Claude deduplicates the overlap zones and
returns one unified process JSON.

Everything runs in-memory — no temp files written to disk.
═══════════════════════════════════════════════════════════════════════════════
"""
import io
import logging

from PIL import Image, ImageEnhance, ImageFilter, ImageStat

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — tuned through testing on real Bupa process diagrams
# ---------------------------------------------------------------------------

TILE_HEIGHT     = 700    # px per tile — tall enough for detail, small enough for clarity
OVERLAP_PCT     = 0.18   # 18% overlap — ensures no step is split across a tile boundary
CONTRAST        = 1.4    # Enhancement values applied to each tile before sending to Claude
SHARPNESS       = 1.8
BRIGHTNESS      = 1.05
TILE_MIN_HEIGHT = 1000   # auto-tile any image taller than this (px)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _score_tile(img: Image.Image) -> dict:
    """PIL-based readability score — no API call needed."""
    gray = img.convert("L")

    stat = ImageStat.Stat(gray)
    contrast_score = min(100, stat.stddev[0] * 2.5)

    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_stat = ImageStat.Stat(edges)
    sharpness_score = min(100, edge_stat.mean[0] * 8)

    pixels = list(gray.getdata())
    non_white = sum(1 for p in pixels if p < 240)
    density_pct = (non_white / len(pixels)) * 100
    if density_pct < 5:
        density_score = density_pct * 10
    elif density_pct <= 30:
        density_score = 100
    else:
        density_score = max(0, 100 - (density_pct - 30) * 3)

    overall = contrast_score * 0.4 + sharpness_score * 0.3 + density_score * 0.3
    return {
        "contrast":    round(contrast_score),
        "sharpness":   round(sharpness_score),
        "density":     round(density_score),
        "density_pct": round(density_pct, 1),
        "overall":     round(overall),
    }


def _enhance(img: Image.Image) -> Image.Image:
    img = ImageEnhance.Contrast(img).enhance(CONTRAST)
    img = ImageEnhance.Sharpness(img).enhance(SHARPNESS)
    img = ImageEnhance.Brightness(img).enhance(BRIGHTNESS)
    return img


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def needs_tiling(image_bytes: bytes) -> bool:
    """
    Return True if the image should be tiled before sending to Claude.
    Tiles when:
      - Image is tall (height > TILE_MIN_HEIGHT), OR
      - PIL readability score is below 65 (dense/blurry content benefits from enhanced tiles)
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.size[1] > TILE_MIN_HEIGHT:
            return True
        scores = _score_tile(img)
        return scores["overall"] < 65
    except Exception:
        return False


def image_dimensions(image_bytes: bytes) -> tuple[int, int]:
    """Return (width, height) of the image, or (0, 0) on error."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        return img.size
    except Exception:
        return (0, 0)


def get_tiling_info(image_bytes: bytes) -> dict:
    """
    Return tiling metadata without performing the tiling.
    Used to annotate confidence events with tiling decisions.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size
        pil_score = _score_tile(img)["overall"]
        will_tile = h > TILE_MIN_HEIGHT or pil_score < 65
        if will_tile:
            overlap_px = int(TILE_HEIGHT * OVERLAP_PCT)
            step = TILE_HEIGHT - overlap_px
            y, count = 0, 0
            while y < h:
                count += 1
                y1 = min(y + TILE_HEIGHT, h)
                if y1 == h:
                    break
                y += step
        else:
            count = 1
        return {"tiled": will_tile, "tile_count": count, "width": w, "height": h}
    except Exception:
        return {"tiled": False, "tile_count": 1, "width": 0, "height": 0}


def tile_image(image_bytes: bytes) -> list[dict]:
    """
    Split an image into overlapping vertical tiles and enhance each one.

    Returns a list of dicts (one per tile, in top-to-bottom order):
        tile_number  : 1-indexed
        total_tiles  : total number of tiles
        bytes        : PNG bytes of the enhanced tile
        y0, y1       : pixel range in the original image
        height_px    : tile height in pixels
        overlap_px   : overlap with the previous tile (0 for tile 1)
    """
    img = Image.open(io.BytesIO(image_bytes))
    w, h = img.size
    overlap_px = int(TILE_HEIGHT * OVERLAP_PCT)
    step = TILE_HEIGHT - overlap_px

    boundaries: list[tuple[int, int]] = []
    y = 0
    while y < h:
        y1 = min(y + TILE_HEIGHT, h)
        boundaries.append((y, y1))
        if y1 == h:
            break
        y += step

    total = len(boundaries)
    tiles: list[dict] = []

    for i, (y0, y1) in enumerate(boundaries):
        tile = img.crop((0, y0, w, y1))
        enhanced = _enhance(tile)
        buf = io.BytesIO()
        enhanced.save(buf, format="PNG", dpi=(150, 150))

        tiles.append({
            "tile_number": i + 1,
            "total_tiles": total,
            "bytes":       buf.getvalue(),
            "y0":          y0,
            "y1":          y1,
            "height_px":   y1 - y0,
            "overlap_px":  overlap_px if i > 0 else 0,
        })

    log.info("Tiled image into %d sections (height=%dpx, tile=%dpx, overlap=%dpx)",
             total, h, TILE_HEIGHT, overlap_px)
    return tiles
