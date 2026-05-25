"""
═══════════════════════════════════════════════════════════════════════════════
PROCESS FORGE — Claude Vision Integration
═══════════════════════════════════════════════════════════════════════════════

This is the heart of Process Forge. It sends diagram images to Claude Vision
(Anthropic's multimodal AI) and receives back a structured JSON description
of the process — swimlanes, steps, gateways, decisions, flows, integrations.

TWO passes are made per image:
  PASS 1 — Confidence Assessment  (CONFIDENCE_PROMPT)
    Claude scores the image across 7 factors and tells us how reliably
    it can extract the content. Score 0-100. Runs before extraction.

  PASS 2 — Process Extraction  (SYSTEM_PROMPT)
    Claude reads the full diagram and returns structured JSON: lanes,
    steps, sequence flows, decisions, data entities, integrations.
    This JSON then feeds all four artefact generators.

Large images are pre-tiled by preprocessor.py before reaching this file.
DEV_MODE bypasses all API calls and returns fixture JSON for testing/demo.
═══════════════════════════════════════════════════════════════════════════════
"""
import asyncio
import base64
import json
import logging
import re
from pathlib import Path
from typing import Optional

import anthropic

from config import settings
from services.preprocessor import needs_tiling, tile_image, get_tiling_info

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DEV_MODE mock layer
#
# When DEV_MODE=true in .env.local, every Claude API call is intercepted here.
# Fixture JSON is returned instead — the rest of the app behaves identically.
# Flip to live mode: ./use-live.sh then restart.
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(_FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def _save_fixture(name: str, data: dict) -> None:
    """Persist data to a fixture file so DEV_MODE can replay it."""
    try:
        _FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
        with open(_FIXTURES_DIR / name, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        log.info("⚙️  Saved fixture: %s", name)
    except Exception as exc:
        log.warning("Could not save fixture %s: %s", name, exc)


def _mock_confidence(filename: str) -> dict:
    # Prefer the last real assessment if one has been saved
    cache_file = "last-assessment.json"
    try:
        cache = _load_fixture(cache_file)
        # last-assessment.json stores a list; pick the first entry (or match by filename)
        entries = cache if isinstance(cache, list) else [cache]
        raw = next((e for e in entries if e.get("filename") == filename), entries[0])
        log.info("⚙️  MOCK MODE — replaying saved assessment for %s", filename)
        return {
            "filename": filename,
            "score": int(raw.get("score", 85)),
            "readability": str(raw.get("readability", "high")),
            "notes": f"[DEV MODE] {raw.get('notes', 'Replayed from last real run.')}",
            "unclear_elements": list(raw.get("unclear_elements", [])),
            "steps": list(raw.get("steps", [])),
        }
    except FileNotFoundError:
        pass
    log.info("⚙️  MOCK MODE — skipping API call [confidence assessment] for %s", filename)
    raw = _load_fixture("confidence-assessment.json")
    return {
        "filename": filename,
        "score": int(raw.get("overall", 85)),
        "readability": str(raw.get("readability", "high")),
        "notes": f"[DEV MODE] {raw.get('notes', 'Mock assessment.')}",
        "unclear_elements": list(raw.get("unclear_elements", [])),
        "steps": list(raw.get("steps", [])),
    }


def _mock_extraction(filename: str) -> tuple[dict, list[str]]:
    # Prefer the last real extraction if one has been saved
    cache_file = "last-extraction.json"
    try:
        data = _load_fixture(cache_file)
        log.info("⚙️  MOCK MODE — replaying saved extraction for %s", filename)
        return data, []
    except FileNotFoundError:
        pass
    log.info("⚙️  MOCK MODE — skipping API call [image extraction] for %s", filename)
    return _load_fixture("image-analysis.json"), []

# ---------------------------------------------------------------------------
# Confidence assessment prompt (separate per-image call)
# ---------------------------------------------------------------------------

CONFIDENCE_PROMPT = """\
You are assessing a business process diagram image to determine how accurately its full content \
can be extracted into a BPMN model. This is NOT just a visual quality check — score every factor below.
Return ONLY valid JSON — no prose, no markdown fences.

{
  "overall": 85,
  "readability": "high",
  "notes": "2-3 sentences covering what was extractable, what was uncertain, and which factors reduced the score.",
  "unclear_elements": [
    "Gateway branch label between steps 4 and 5 is cut off",
    "Swimlane boundary between Agent and Customer is ambiguous in the middle section",
    "Arrow direction from step 9 is unclear — could connect to two different steps"
  ],
  "steps": [
    {"source_ref": "6.2.3.1.1", "name": "Add a person to a policy", "type": "subprocess"},
    {"source_ref": "6.2.3.1.2", "name": "Verify eligibility", "type": "task"}
  ]
}

Score as an integer 0-100 by evaluating ALL seven factors and averaging:

  1. Image resolution & sharpness  — is the image clear enough to read small text and thin arrows?
  2. Step/task label legibility     — can every rectangle/rounded-rect label be read with certainty?
  3. Flow arrow clarity             — are all sequence arrows unambiguous in direction and destination?
  4. Swimlane structure             — are lane borders distinct and role labels fully readable?
  5. Gateway & decision legibility  — are diamond shapes and ALL their branch labels fully visible?
  6. Process completeness           — is the full process visible with no cut-off edges or missing sections?
  7. Structural density             — are shapes well-separated, or do overlaps/crowding obscure the flow?

Scoring bands (apply to the average across all 7 factors — do NOT inflate):
  90-100 : Excellent on all factors — extraction will be highly accurate
  70-89  : Good overall; 1-2 minor issues in isolated areas — minor gaps possible
  50-69  : Multiple factors impaired — several steps/labels/flows uncertain — significant extraction gaps expected
  30-49  : Most factors poor — majority of content uncertain — extraction will be largely guesswork
  0-29   : Unable to reliably extract — labels, flow, or swimlanes are largely unreadable

readability (set based on factors 1, 2, and 7 combined):
  "high"   — sharp text, clear boxes and arrows throughout
  "medium" — readable overall but with noticeable blur, overlap, or cut-off elements
  "low"    — significant readability problems affecting most of the diagram

unclear_elements: list EVERY specific label, gateway branch, arrow, or swimlane boundary you \
could not read or trace with confidence. Be specific (e.g. "Step 6 label obscured by overlap", \
not "some labels unclear"). Use [] only if genuinely everything was clear.

steps: list every step that has a visible reference number shown on or beside it (e.g. "6.2.3.1.1").
- source_ref: the reference number only (digits and dots, e.g. "6.2.3.1.1")
- name: the step label text WITHOUT the reference number prefix
- type: "task" | "gateway" | "event" | "subprocess"
Omit steps with no visible reference number. Return [] if none are found.
"""

# ---------------------------------------------------------------------------
# SYSTEM_PROMPT — The extraction instruction set sent to Claude Vision
#
# This is prompt engineering as software engineering. Every rule here was
# written to handle a specific edge case found in real Bupa process diagrams:
#
#   - Lane headers with multiple stacked role names  → take the first only
#   - Subprocess classification                      → child_case vs inline
#   - Reference numbers on step labels               → split to source_ref + name
#   - Multiple diagram images                        → merge into one process
#   - Gateways with named branches                  → preserve branch order
#
# Claude Vision receives this as its "system" role — it sets the context
# before the image is sent. Claude then returns ONLY the JSON object.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a business process analyst specialising in BPMN 2.0 modelling for Bupa Health Insurance.
You will be given one or more PNG images of Bupa process flow diagrams.

Extract the process into a precise JSON object.
Return ONLY valid JSON — no prose, no markdown fences, no commentary.

JSON schema:

{
  "process_name": "string — full descriptive name of the process",
  "lanes": ["string — concise name of each swimlane (see lane rules below)"],
  "steps": [
    {
      "id": "string — unique snake_case id e.g. step_1",
      "type": "task | gateway | event | subprocess",
      "subtype": "child_case | inline  (only present when type == subprocess)",
      "name": "string — exact label from the diagram, WITHOUT any leading reference number",
      "source_ref": "string | null — the process reference number visible on or near this step (e.g. '6.2.2.1', '6.2.3.1.2'). Null if none is shown.",
      "lane": "string — must match one entry in lanes[] exactly",
      "sequence": ["string — id(s) of the next step(s) in flow order"]
    }
  ],
  "data_entities": ["string — data stores, documents or data objects referenced"],
  "integrations": ["string — external systems, applications or APIs named"],
  "decisions": [
    {
      "id": "string — must match the gateway step id exactly",
      "question": "string — the decision question on the diamond",
      "outcomes": ["string — label on each outgoing branch, in the same order as sequence[]"]
    }
  ],
  "confidence": {
    "overall": 85,
    "readability": "high",
    "notes": "Brief description of diagram clarity and any areas of uncertainty"
  },
  "confidence_per_image": [
    { "diagram_index": 1, "overall": 90, "readability": "high", "notes": "..." }
  ]
}

Confidence rules:
- overall: integer 0-100 reflecting your confidence in extraction accuracy
- readability: "high" (clear labels, good resolution), "medium" (some labels unclear), "low" (poor resolution or heavily overlapping shapes)
- notes: 1-2 sentences on what was clear, what was uncertain, and any elements you could not read reliably
- For a single image, populate "confidence" only. For multiple images, populate "confidence_per_image" (one entry per diagram, in order) AND "confidence" as the overall average.

Strict rules:
1. LANE NAMES — each swimlane row in the diagram becomes ONE entry in lanes[].
   - Use the PRIMARY role name only (e.g. "Agent", "Customer", "HI Partnership Solutions Consultant").
   - Swimlane headers that list multiple roles (separated by commas, slashes, &, or "and") → use ONLY the FIRST role.
   - Keep lane names under 50 characters. Do NOT include any separators, lists, or multiple roles.
   - Each step's "lane" must match one entry in lanes[] exactly.
2. Step types:
   - Rounded rectangle / rectangle = "task"
   - Diamond shape = "gateway" (MUST have a matching entry in decisions[])
   - Oval / circle (start/end markers) = "event"
   - A step that calls or links to a separate named sub-process = "subprocess"
     Sub-type classification (recorded in the step's "subtype" field):
       - "child_case"  → will map to BPMN <callActivity>  (the subprocess runs as an independent case)
       - "inline"      → will map to BPMN <subProcess>    (the subprocess is part of the same case)
     Default to "inline" unless the user's Process Instructions specify otherwise.
3. The first step in each lane is type "event" (start). The last is type "event" (end).
4. For every gateway, decisions[] must have an entry whose "outcomes" list matches the branch labels in the SAME ORDER as the step's "sequence" array.
5. Copy step labels verbatim from the diagram — do not paraphrase or shorten.
   If the label begins with a reference number (e.g. "6.2.2.1 Add a person to a policy"),
   put the reference number in source_ref and the remaining label text in name.
6. source_ref: capture any process reference number (digits and dots, e.g. "6.2.3.1.2") that
   appears on, inside, or directly beside a step box. Set to null if none is visible.
7. Do not invent steps not visible in the diagram. Use "Unknown Step N" only when a label is genuinely unreadable.
8. If multiple PNGs are provided, merge into one coherent process, re-numbering ids from step_1.
   Consolidate lanes with the same role across diagrams into a single lane entry.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_base64(image_bytes: bytes) -> str:
    return base64.standard_b64encode(image_bytes).decode("utf-8")


def _repair_truncated_json(text: str) -> str:
    """
    Attempt to repair JSON that was cut off mid-stream (e.g. by max_tokens).
    Closes any open strings, arrays and objects so json.loads can parse it.
    """
    stack: list[str] = []
    in_string = False
    escape = False

    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "]}":
            if stack and stack[-1] == ch:
                stack.pop()

    if in_string:
        text += '"'
    while stack:
        text += stack.pop()
    return text


def _strip_trailing_commas(text: str) -> str:
    """Remove trailing commas before } or ] (common Claude JSON quirk)."""
    return re.sub(r",(\s*[}\]])", r"\1", text)


def _extract_json(text: str) -> dict:
    """
    Extract the first JSON object from Claude's response.
    Handles markdown fences, trailing commas, and truncated JSON.
    """
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start = cleaned.find("{")
    if start == -1:
        raise ValueError("No JSON object found in Claude response.")

    candidate = cleaned[start:]

    # Try as-is first
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Try with trailing commas removed
    no_trailing = _strip_trailing_commas(candidate)
    try:
        return json.loads(no_trailing)
    except json.JSONDecodeError:
        pass

    # Try after repair (closes open brackets/strings)
    repaired = _repair_truncated_json(no_trailing)
    return json.loads(repaired)


def _merge_process_data(results: list[dict]) -> dict:
    """
    Merge process data from multiple sequential diagrams into a single object.
    - Re-ids all steps to avoid collisions.
    - Chains the end events of diagram N into the start events of diagram N+1
      so the workflow flows continuously end-to-end.
    """
    if len(results) == 1:
        return results[0]

    merged = {
        "process_name": results[0].get("process_name", "Merged Process"),
        "lanes": [],
        "steps": [],
        "data_entities": [],
        "integrations": [],
        "decisions": [],
    }

    step_counter = 1
    # First pass: build id maps for all results so we can wire cross-diagram links
    all_id_maps: list[dict[str, str]] = []
    for result in results:
        id_map: dict[str, str] = {}
        for step in result.get("steps", []):
            id_map[step["id"]] = f"step_{step_counter}"
            step_counter += 1
        all_id_maps.append(id_map)

    # Second pass: emit steps and wire end→start between diagrams
    for i, (result, id_map) in enumerate(zip(results, all_id_maps)):
        steps = result.get("steps", [])

        # Find end events of this diagram (type==event, no outgoing sequence)
        end_ids = {
            s["id"] for s in steps
            if s.get("type") == "event" and not s.get("sequence")
        }

        # Find start events of the NEXT diagram
        next_start_ids: list[str] = []
        if i + 1 < len(results):
            next_steps = results[i + 1].get("steps", [])
            next_id_map = all_id_maps[i + 1]
            next_incoming = {
                seq
                for s in next_steps
                for seq in s.get("sequence", [])
            }
            next_start_ids = [
                next_id_map[s["id"]]
                for s in next_steps
                if s.get("type") == "event" and s["id"] not in next_incoming
            ]

        for step in steps:
            new_id = id_map[step["id"]]
            seq = [id_map.get(s, s) for s in step.get("sequence", [])]

            # If this is an end event and there's a next diagram, chain into it
            if step["id"] in end_ids and next_start_ids:
                seq = next_start_ids  # replace empty sequence with next diagram's starts

            merged["steps"].append({
                "id": new_id,
                "type": step["type"],
                "name": step["name"],
                "lane": step.get("lane", ""),
                "sequence": seq,
            })

        # Lanes
        for lane in result.get("lanes", []):
            if lane not in merged["lanes"]:
                merged["lanes"].append(lane)

        # Data entities & integrations
        for entity in result.get("data_entities", []):
            if entity not in merged["data_entities"]:
                merged["data_entities"].append(entity)
        for integration in result.get("integrations", []):
            if integration not in merged["integrations"]:
                merged["integrations"].append(integration)

        # Decisions (re-mapped ids)
        for decision in result.get("decisions", []):
            merged["decisions"].append({
                "id": id_map.get(decision["id"], decision["id"]),
                "question": decision["question"],
                "outcomes": decision["outcomes"],
            })

    return merged


def _empty_process() -> dict:
    return {
        "process_name": "Unknown Process",
        "lanes": ["Default"],
        "steps": [
            {"id": "step_1", "type": "event", "name": "Start", "lane": "Default", "sequence": ["step_2"]},
            {"id": "step_2", "type": "event", "name": "End", "lane": "Default", "sequence": []},
        ],
        "data_entities": [],
        "integrations": [],
        "decisions": [],
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def _api_call_with_retry(coro_fn, label: str, max_retries: int = 3):
    """
    Call an async API function, retrying on rate-limit (429) errors with
    exponential backoff.  Other errors are re-raised immediately.
    """
    for attempt in range(max_retries):
        try:
            return await coro_fn()
        except anthropic.RateLimitError as exc:
            if attempt == max_retries - 1:
                raise
            delay = 10 * (2 ** attempt)   # 10s, 20s, 40s
            log.warning("Rate limit hit for %s — retrying in %ds (attempt %d/%d)",
                        label, delay, attempt + 1, max_retries)
            await asyncio.sleep(delay)


def _safe_score(val) -> int:
    """Convert whatever Claude returns for a score into an int 0-100."""
    try:
        return max(0, min(100, int(float(str(val)))))
    except Exception:
        return 50


def _default_confidence(filename: str) -> dict:
    return {
        "filename": filename,
        "score": 50,
        "readability": "medium",
        "notes": "Confidence data not returned by model.",
        "steps_extracted": 0,
        "lanes_identified": 0,
        "gateways_found": 0,
        "decisions_extracted": 0,
        "warnings": [],
    }


def _extract_confidence(process_data: dict, filename: str) -> dict:
    """
    Pull the confidence block out of process_data and normalise.
    Always returns a complete dict — never raises.
    """
    try:
        raw = process_data.pop("confidence", None) or {}
        return {
            "filename": filename,
            "score": _safe_score(raw.get("overall", 50)),
            "readability": str(raw.get("readability", "medium")).lower(),
            "notes": str(raw.get("notes", "")) or "No notes provided.",
        }
    except Exception:
        return _default_confidence(filename)


def _build_confidence_list(
    process_data: dict,
    diagram_bytes: list[tuple[str, bytes]],
) -> list[dict]:
    """
    Build a per-image confidence list — one entry per input image, always.
    Tries confidence_per_image[] first (multi-image), then confidence{} (single),
    then falls back to defaults. Never raises.
    """
    filenames = [fn for fn, _ in diagram_bytes]

    try:
        per_image = process_data.pop("confidence_per_image", None)
        if per_image and isinstance(per_image, list) and len(per_image) > 0:
            entries = []
            for i, fn in enumerate(filenames):
                if i < len(per_image):
                    entry = per_image[i] if isinstance(per_image[i], dict) else {}
                else:
                    entry = {}
                entries.append({
                    "filename": fn,
                    "score": _safe_score(entry.get("overall", 50)),
                    "readability": str(entry.get("readability", "medium")).lower(),
                    "notes": str(entry.get("notes", "")) or "No notes provided.",
                })
            process_data.pop("confidence", None)
            return entries

        # No per_image — use overall confidence for all images
        raw = process_data.pop("confidence", None) or {}
        score = _safe_score(raw.get("overall", 50))
        readability = str(raw.get("readability", "medium")).lower()
        notes = str(raw.get("notes", "")) or "No notes provided."
        return [
            {"filename": fn, "score": score, "readability": readability, "notes": notes}
            for fn in filenames
        ]
    except Exception:
        return [_default_confidence(fn) for fn in filenames]


def _enrich_confidence(conf: dict, process_data: dict, img_warnings: list[str]) -> dict:
    """Add extraction stats to a confidence dict. Never raises."""
    try:
        steps = process_data.get("steps", [])
        subprocesses = [s for s in steps if s.get("type") == "subprocess"]
        conf["steps_extracted"]    = len(steps)
        conf["lanes_identified"]   = len(process_data.get("lanes", []))
        conf["gateways_found"]     = sum(1 for s in steps if s.get("type") == "gateway")
        conf["decisions_extracted"] = len(process_data.get("decisions", []))
        conf["subprocesses_found"] = len(subprocesses)
        conf["child_cases"]        = sum(1 for s in subprocesses if s.get("subtype") == "child_case")
        conf["warnings"] = img_warnings
    except Exception:
        conf.setdefault("steps_extracted", 0)
        conf.setdefault("lanes_identified", 0)
        conf.setdefault("gateways_found", 0)
        conf.setdefault("decisions_extracted", 0)
        conf.setdefault("subprocesses_found", 0)
        conf.setdefault("child_cases", 0)
        conf.setdefault("warnings", [])
    return conf


def _assess_image_confidence(
    client: anthropic.Anthropic,
    filename: str,
    image_bytes: bytes,
) -> dict:
    """
    Dedicated per-image confidence assessment call.
    Uses a focused rubric prompt so Claude genuinely evaluates each image
    rather than returning a generic shared score.
    Never raises — falls back to a neutral default on any error.
    """
    try:
        media_type = _detect_media_type(image_bytes, filename)
        response = client.messages.create(
            model=settings.effective_model,
            max_tokens=512,
            temperature=0,
            system=CONFIDENCE_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": _to_base64(image_bytes),
                        },
                    },
                    {
                        "type": "text",
                        "text": f"Assess the readability and confidence of extraction for: {filename}",
                    },
                ],
            }],
        )
        if not response.content:
            raise ValueError("Empty response")

        raw = _extract_json(response.content[0].text)
        return {
            "filename": filename,
            "score": _safe_score(raw.get("overall", 50)),
            "readability": str(raw.get("readability", "medium")).lower(),
            "notes": str(raw.get("notes", "")).strip() or "No notes provided.",
            "unclear_elements": [str(e) for e in raw.get("unclear_elements", [])],
        }
    except Exception as exc:
        log.warning("Confidence assessment failed for %s: %s", filename, exc)
        return {
            "filename": filename,
            "score": 50,
            "readability": "medium",
            "notes": "Confidence assessment could not be completed.",
            "unclear_elements": [],
        }


def _pil_confidence(filename: str, image_bytes: bytes) -> dict:
    """
    Deterministic PIL-based confidence score for tiled images.
    Scores each tile independently and averages — avoids Claude non-determinism
    on borderline images that get split.
    """
    from services.preprocessor import tile_image as _tile_image, _score_tile
    from PIL import Image
    import io

    try:
        tiles = _tile_image(image_bytes)
        scores = []
        for tile in tiles:
            img = Image.open(io.BytesIO(tile["bytes"]))
            scores.append(_score_tile(img)["overall"])
        avg = round(sum(scores) / len(scores))
        readability = "high" if avg >= 70 else "medium" if avg >= 50 else "low"
        tile_scores = " · ".join(f"Tile {i+1}: {s}%" for i, s in enumerate(scores))
        return {
            "filename": filename,
            "score": avg,
            "readability": readability,
            "notes": f"PIL-based score averaged across {len(tiles)} tiles ({tile_scores}). "
                     "Consistent across assess and generate runs.",
            "unclear_elements": [],
        }
    except Exception as exc:
        log.warning("PIL confidence failed for %s: %s", filename, exc)
        return {
            "filename": filename, "score": 50, "readability": "medium",
            "notes": "PIL confidence assessment could not be completed.", "unclear_elements": [],
        }


async def _assess_tile_confidence_async(
    client: anthropic.AsyncAnthropic,
    filename: str,
    tile_bytes: bytes,
    tile_index: int,
) -> dict:
    """Assess a single tile using the Claude 7-factor rubric."""
    if settings.dev_mode:
        log.info("⚙️  MOCK MODE — skipping API call [tile confidence tile=%d] for %s", tile_index, filename)
        raw = _load_fixture("confidence-assessment.json")
        return {
            "score": int(raw.get("overall", 85)),
            "readability": str(raw.get("readability", "high")),
            "notes": raw.get("notes", ""),
            "unclear_elements": [],
        }
    try:
        media_type = _detect_media_type(tile_bytes, filename)
        label = f"tile {tile_index} of {filename}"

        async def _call():
            return await client.messages.create(
                model=settings.effective_model,
                max_tokens=1000,
                temperature=0,
                system=CONFIDENCE_PROMPT,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": _to_base64(tile_bytes)},
                        },
                        {
                            "type": "text",
                            "text": f"Assess extraction confidence for tile {tile_index} of: {filename}",
                        },
                    ],
                }],
            )

        response = await _api_call_with_retry(_call, label)
        if not response.content:
            raise ValueError("Empty response")
        raw = _extract_json(response.content[0].text)
        return {
            "score": _safe_score(raw.get("overall", 50)),
            "readability": str(raw.get("readability", "medium")).lower(),
            "notes": str(raw.get("notes", "")).strip(),
            "unclear_elements": [str(e) for e in raw.get("unclear_elements", [])],
            "steps": [s for s in raw.get("steps", []) if isinstance(s, dict) and s.get("source_ref")],
        }
    except Exception as exc:
        log.warning("Tile %d confidence assessment failed for %s: %s", tile_index, filename, exc)
        return {"score": 50, "readability": "medium", "notes": "", "unclear_elements": [], "steps": []}


async def _assess_image_confidence_async(
    client: anthropic.AsyncAnthropic,
    filename: str,
    image_bytes: bytes,
) -> dict:
    """
    Confidence assessment for a single image using the 7-factor Claude rubric.
    Tiled images are assessed tile-by-tile via Claude and averaged — no PIL shortcut.
    """
    if settings.dev_mode:
        return _mock_confidence(filename)

    if needs_tiling(image_bytes):
        log.info("Assessing tiled image via Claude: %s", filename)
        tiles = tile_image(image_bytes)
        results = []
        for i, tile in enumerate(tiles, start=1):
            r = await _assess_tile_confidence_async(client, filename, tile["bytes"], i)
            results.append(r)

        avg_score = round(sum(r["score"] for r in results) / len(results))
        # Overall readability: worst of any tile
        def _rl(r): return {"high": 2, "medium": 1, "low": 0}.get(r["readability"], 1)
        worst_rl = min(results, key=_rl)["readability"]
        tile_scores = " · ".join(f"Tile {i+1}: {r['score']}%" for i, r in enumerate(results))
        all_unclear = [el for r in results for el in r["unclear_elements"]]
        all_steps = [s for r in results for s in r.get("steps", [])]
        notes_parts = [r["notes"] for r in results if r["notes"]]
        combined_notes = " ".join(notes_parts[:2]) if notes_parts else "Multi-tile assessment completed."
        combined_notes += f" (Tiles: {tile_scores})"
        return {
            "filename": filename,
            "score": avg_score,
            "readability": worst_rl,
            "notes": combined_notes,
            "unclear_elements": all_unclear,
            "steps": all_steps,
        }

    try:
        media_type = _detect_media_type(image_bytes, filename)

        async def _call():
            return await client.messages.create(
                model=settings.effective_model,
                max_tokens=1500,
                temperature=0,
                system=CONFIDENCE_PROMPT,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": _to_base64(image_bytes)},
                        },
                        {
                            "type": "text",
                            "text": f"Assess the extraction confidence for: {filename}",
                        },
                    ],
                }],
            )

        response = await _api_call_with_retry(_call, filename)
        if not response.content:
            raise ValueError("Empty response")
        raw = _extract_json(response.content[0].text)
        return {
            "filename": filename,
            "score": _safe_score(raw.get("overall", 50)),
            "readability": str(raw.get("readability", "medium")).lower(),
            "notes": str(raw.get("notes", "")).strip() or "No notes provided.",
            "unclear_elements": [str(e) for e in raw.get("unclear_elements", [])],
            "steps": [s for s in raw.get("steps", []) if isinstance(s, dict) and s.get("source_ref")],
        }
    except Exception as exc:
        log.warning("Confidence assessment failed for %s: %s", filename, exc)
        return {
            "filename": filename, "score": 50, "readability": "medium",
            "notes": "Confidence assessment could not be completed.", "unclear_elements": [],
            "steps": [],
        }


async def _call_claude_single_async(
    client: anthropic.AsyncAnthropic,
    filename: str,
    image_bytes: bytes,
    process_instructions: Optional[str] = None,
) -> tuple[dict, list[str]]:
    """Async version of _call_claude_single. Auto-tiles tall images before extraction."""
    if settings.dev_mode:
        return _mock_extraction(filename)

    if needs_tiling(image_bytes):
        log.info("Auto-tiling %s for extraction", filename)
        tiles = tile_image(image_bytes)
        return await _call_claude_tiled_async(client, filename, tiles, process_instructions)

    warnings: list[str] = []
    media_type = _detect_media_type(image_bytes, filename)

    instruction_block = ""
    if process_instructions and process_instructions.strip():
        instruction_block = (
            f"\n\nProcess instructions from the user:\n{process_instructions.strip()}\n"
            "Apply these instructions when classifying subprocesses: use <callActivity> for child cases "
            "and <subProcess> for inline subprocesses as specified."
        )

    try:
        response = await client.messages.create(
            model=settings.effective_model,
            max_tokens=8096,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": _to_base64(image_bytes)},
                    },
                    {
                        "type": "text",
                        "text": (
                            f"Analyse this process flow diagram ({filename}) "
                            f"and return the structured JSON as instructed.{instruction_block}"
                        ),
                    },
                ],
            }],
        )
        raw_text = response.content[0].text
        process_data = _extract_json(raw_text)
        _validate_process_data(process_data)
        return process_data, warnings
    except json.JSONDecodeError as exc:
        warnings.append(f"{filename}: Claude returned invalid JSON — using fallback. ({exc})")
        return _empty_process(), warnings
    except ValueError as exc:
        warnings.append(f"{filename}: Validation failed — {exc}. Using fallback.")
        return _empty_process(), warnings
    except anthropic.APIError as exc:
        # Re-raise API errors (SSL failures, auth errors, Zscaler interception) —
        # do NOT fall back silently or the caller gets a useless empty BPMN.
        log.error("Claude API error for %s: %s", filename, exc)
        raise


async def _call_claude_tiled_async(
    client: anthropic.AsyncAnthropic,
    filename: str,
    tiles: list[dict],
    process_instructions: Optional[str] = None,
) -> tuple[dict, list[str]]:
    """
    Extract process data from a tiled image.
    Sends all tiles in one Claude call with positional context so Claude
    can deduplicate overlap zones and return a single unified process.
    """
    if settings.dev_mode:
        return _mock_extraction(filename)

    warnings: list[str] = []
    n = len(tiles)

    instruction_block = ""
    if process_instructions and process_instructions.strip():
        instruction_block = (
            f"\n\nProcess instructions from the user:\n{process_instructions.strip()}\n"
            "Apply these instructions when classifying subprocesses."
        )

    content: list[dict] = []
    for tile in tiles:
        media_type = _detect_media_type(tile["bytes"], filename)
        overlap_note = (
            f", overlaps {tile['overlap_px']}px with previous tile" if tile["overlap_px"] > 0 else ""
        )
        content.append({
            "type": "text",
            "text": (
                f"Tile {tile['tile_number']} of {n} from '{filename}' "
                f"(rows {tile['y0']}–{tile['y1']}px of the original image{overlap_note})"
            ),
        })
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": _to_base64(tile["bytes"])},
        })

    content.append({
        "type": "text",
        "text": (
            f"These {n} tiles are consecutive vertical sections of a single process diagram '{filename}'. "
            f"Each tile overlaps slightly with the next to preserve flow continuity at the joins. "
            f"Extract the COMPLETE process across all tiles into ONE unified JSON object. "
            f"Deduplicate any steps that appear in the overlap zones — keep each step only once. "
            f"Number step ids sequentially from step_1 across all tiles."
            f"{instruction_block}"
        ),
    })

    try:
        response = await client.messages.create(
            model=settings.effective_model,
            max_tokens=8096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
        raw_text = response.content[0].text
        process_data = _extract_json(raw_text)
        _validate_process_data(process_data)
        log.info("Tiled extraction complete: %s (%d tiles → %d steps)",
                 filename, n, len(process_data.get("steps", [])))
        return process_data, warnings
    except json.JSONDecodeError as exc:
        warnings.append(f"{filename}: Invalid JSON from tiled extraction — using fallback. ({exc})")
        return _empty_process(), warnings
    except ValueError as exc:
        warnings.append(f"{filename}: Validation failed on tiled extraction — {exc}. Using fallback.")
        return _empty_process(), warnings
    except anthropic.APIError as exc:
        log.error("Claude API error for tiled %s: %s", filename, exc)
        raise


async def assess_images_stream(
    diagram_bytes: list[tuple[str, bytes]],
):
    """
    Async generator — yields typed event dicts:
      {"type": "confidence", "data": {...}}   — one per image
      {"type": "ref_map",    "data": {...}}   — once at the end, includes:
            nodes          — aggregated sorted ref nodes
            gaps           — missing parent / sibling gap warnings
            image_refs     — {filename: [ref, ...]} — which refs came from which diagram
            suggested_order — filenames sorted by call-graph topology (callers
                              before callees), falling back to ref-number sort
                              for images with no call-graph edges
    Used by the /api/assess pre-flight endpoint.
    """
    from utils.ref_utils import (
        build_ref_nodes, detect_gaps, ref_sort_key, extract_refs_from_text,
        build_call_graph, topo_sort_images, identity_from_filename,
    )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    all_steps: list[dict] = []
    all_fallback_texts: list[str] = []
    all_conf_results: list[dict] = []                  # accumulated for auto-save
    image_refs: dict[str, list[str]] = {}              # filename → [all source_refs]
    image_subprocess_calls: dict[str, list[str]] = {}  # filename → [subprocess source_refs]

    # Run all confidence assessments in parallel (max 2 concurrent to respect rate limits)
    sem = asyncio.Semaphore(2)

    async def _assess_one(fn: str, img: bytes) -> tuple[str, bytes, dict]:
        async with sem:
            conf = await _assess_image_confidence_async(client, fn, img)
            return fn, img, conf

    tasks = [asyncio.create_task(_assess_one(fn, img)) for fn, img in diagram_bytes]

    for coro in asyncio.as_completed(tasks):
        filename, _, conf = await coro
        steps = conf.pop("steps", [])

        # Per-image text for fallback ref extraction
        img_texts: list[str] = []
        if conf.get("notes"):
            img_texts.append(conf["notes"])
        img_texts.extend(conf.get("unclear_elements", []))

        # Build per-image ref list (explicit steps first, fallback if none)
        has_explicit = any(s.get("source_ref") for s in steps)
        img_nodes = build_ref_nodes(steps, fallback_texts=img_texts if not has_explicit else None)
        img_ref_list = [n["source_ref"] for n in img_nodes]

        # Guarantee the filename-based identity is always in the ref set.
        # Prevents false gap warnings when Claude extracts a process's children
        # but not the process ref itself (e.g. extracts 6.2.8.2.1–8 but not 6.2.8.2).
        fn_identity = identity_from_filename(filename)
        if fn_identity and fn_identity not in img_ref_list:
            img_ref_list = [fn_identity] + img_ref_list
            all_steps.append({"source_ref": fn_identity, "name": "", "type": "task"})

        if img_ref_list:
            image_refs[filename] = img_ref_list

        # Track which subprocess refs this image calls — used for call-graph ordering
        subprocess_refs = [
            s["source_ref"] for s in steps
            if s.get("type") == "subprocess" and s.get("source_ref")
        ]
        if subprocess_refs:
            image_subprocess_calls[filename] = subprocess_refs

        all_steps.extend(steps)
        all_fallback_texts.extend(img_texts)

        log.info("Pre-flight assessment: %s score=%s refs_found=%d subprocess_calls=%d",
                 filename, conf.get("score"), len(img_ref_list), len(subprocess_refs))
        all_conf_results.append(conf)
        yield {"type": "confidence", "data": conf}

    # Auto-save so DEV_MODE can replay this assess run
    if not settings.dev_mode and all_conf_results:
        _save_fixture("last-assessment.json", all_conf_results)

    # Aggregate across all images
    nodes = build_ref_nodes(all_steps, fallback_texts=all_fallback_texts)
    gaps  = detect_gaps(nodes)

    # Build call graph and topologically sort: callers before callees
    call_graph    = build_call_graph(image_refs, image_subprocess_calls)
    suggested_order = topo_sort_images(image_refs, call_graph)

    edges_found = sum(len(v) for v in call_graph.values())
    log.info("Call graph: %d edges — suggested_order=%s", edges_found, suggested_order)

    # Build ref-level call graph for frontend flow visualisation.
    # Converts filename→[filenames] edges to ref→[refs] using filename identities.
    ref_call_graph: dict[str, list[str]] = {}
    for fn, called_fns in call_graph.items():
        from_ref = identity_from_filename(fn)
        if from_ref:
            to_refs = [r for f in called_fns if (r := identity_from_filename(f))]
            if to_refs:
                ref_call_graph[from_ref] = to_refs

    log.info("Ref map built: %d nodes, %d gaps, %d call-graph edges",
             len(nodes), len(gaps), sum(len(v) for v in ref_call_graph.values()))
    yield {"type": "ref_map", "data": {
        "nodes": nodes,
        "gaps": gaps,
        "image_refs": image_refs,
        "suggested_order": suggested_order,
        "call_graph": ref_call_graph,
    }}


async def analyse_diagrams_stream(
    diagram_bytes: list[tuple[str, bytes]],
    process_instructions: Optional[str] = None,
    cached_confidence: Optional[dict] = None,
):
    """
    Async generator. Yields one dict per image as it completes:
      {"type": "image", "confidence": {...}, "warnings": [...]}
    Then a final dict when all images are done:
      {"type": "done", "process_data": {...}, "warnings": [...], "all_confidence": [...]}

    cached_confidence: optional dict mapping filename → confidence dict from a prior
    Assess run. When provided, skips the confidence API call for that image.
    """
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    all_confidence: list[dict] = []
    all_results: list[dict] = []
    all_warnings: list[str] = []

    log.info("Streaming per-image analysis for %d image(s)...", len(diagram_bytes))

    for filename, image_bytes in diagram_bytes:
        tiling = get_tiling_info(image_bytes)
        yield {"type": "image_start", "filename": filename, "tiling": tiling}
        if cached_confidence and filename in cached_confidence:
            log.info("Using cached confidence for %s (skipping re-assessment)", filename)
            conf = dict(cached_confidence[filename])
            yield {"type": "detail", "message": f"✓ Confidence cached from Assess run — skipping re-assessment"}
        else:
            log.info("No cached confidence for %s — running assessment", filename)
            conf = await _assess_image_confidence_async(client, filename, image_bytes)
        result, warnings = await _call_claude_single_async(client, filename, image_bytes, process_instructions)
        result.pop("confidence", None)
        result.pop("confidence_per_image", None)
        _enrich_confidence(conf, result, warnings)
        conf["tiled"]        = tiling["tiled"]
        conf["tile_count"]   = tiling["tile_count"]
        conf["image_width"]  = tiling["width"]
        conf["image_height"] = tiling["height"]
        if tiling["tiled"]:
            log.info("Tiling confirmed: %s split into %d tiles (%dx%dpx)",
                     filename, tiling["tile_count"], tiling["width"], tiling["height"])
        all_confidence.append(conf)
        all_results.append(result)
        all_warnings.extend(warnings)
        log.info("Image complete: %s (score=%s)", filename, conf.get("score"))
        yield {"type": "image", "confidence": conf, "warnings": warnings}

    merged = _merge_process_data(all_results) if len(all_results) > 1 else all_results[0]

    # Auto-save so DEV_MODE can replay this run without hitting the API again
    if not settings.dev_mode:
        _save_fixture("last-extraction.json", merged)

    yield {"type": "done", "process_data": merged, "warnings": all_warnings, "all_confidence": all_confidence}


async def analyse_diagrams(
    diagram_bytes: list[tuple[str, bytes]],
    process_instructions: Optional[str] = None,
) -> tuple[dict, list[str], list[dict]]:
    """Collect all results from analyse_diagrams_stream and return as a tuple."""
    all_confidence: list[dict] = []
    all_warnings: list[str] = []
    process_data: dict = {}

    async for event in analyse_diagrams_stream(diagram_bytes, process_instructions):
        if event["type"] == "image":
            all_confidence.append(event["confidence"])
            all_warnings.extend(event.get("warnings", []))
        elif event["type"] == "done":
            process_data = event["process_data"]

    return process_data, all_warnings, all_confidence


def _build_image_content_blocks(
    diagram_bytes: list[tuple[str, bytes]],
) -> list[dict]:
    """Build the reusable image + label content blocks for a Claude message."""
    n = len(diagram_bytes)
    content: list[dict] = []
    for i, (filename, image_bytes) in enumerate(diagram_bytes):
        media_type = _detect_media_type(image_bytes, filename)
        content.append({"type": "text", "text": f"Diagram {i + 1} of {n}: {filename}"})
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": _to_base64(image_bytes),
            },
        })
    return content


def _call_claude_multi(
    client: anthropic.Anthropic,
    diagram_bytes: list[tuple[str, bytes]],
) -> dict:
    """
    Send all images in one message, asking Claude to treat them as a single sequential workflow.
    If the first call returns empty decisions (token budget pressure), a targeted second call
    extracts just the decisions and merges them in.
    """
    n = len(diagram_bytes)
    content = _build_image_content_blocks(diagram_bytes)
    content.append({
        "type": "text",
        "text": (
            f"I am providing {n} process flow diagrams that form a SINGLE sequential workflow — "
            f"diagram 1 feeds into diagram 2, which feeds into diagram 3, and so on. "
            f"Analyse all {n} diagrams together and return ONE unified JSON object representing "
            f"the complete end-to-end process. "
            f"Ensure the end steps of each diagram connect (via sequence[]) to the start steps "
            f"of the next diagram. Number all step ids sequentially from step_1 across all diagrams. "
            f"You MUST populate the decisions[] array for every gateway diamond — include the "
            f"decision question and the branch outcome labels in the same order as sequence[]."
        ),
    })

    response = client.messages.create(
        model=settings.effective_model,
        max_tokens=8096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )

    if not response.content:
        raise ValueError("Claude returned an empty response (no content blocks).")

    raw_text = response.content[0].text
    process_data = _extract_json(raw_text)
    _validate_process_data(process_data)

    # If decisions are empty but there are gateway steps, do a targeted second pass
    gateways = [s for s in process_data.get("steps", []) if s.get("type") == "gateway"]
    if gateways and not process_data.get("decisions"):
        try:
            decisions = _call_claude_decisions(client, diagram_bytes, gateways)
            if decisions:
                process_data["decisions"] = decisions
        except Exception:
            pass  # Non-fatal — structure is still valid without branch labels

    return process_data


def _call_claude_decisions(
    client: anthropic.Anthropic,
    diagram_bytes: list[tuple[str, bytes]],
    gateways: list[dict],
) -> list[dict]:
    """
    Targeted second pass: extract decision branch labels for each gateway.
    Returns a list of decision dicts compatible with the main process_data schema.
    """
    gateway_list = "\n".join(
        f'  id="{g["id"]}" name="{g.get("name", "Gateway")}"'
        for g in gateways
    )

    content = _build_image_content_blocks(diagram_bytes)
    content.append({
        "type": "text",
        "text": (
            "I have already extracted the process steps from these diagrams. "
            "Now I need the decision branch labels for each gateway diamond.\n\n"
            "Gateways identified:\n"
            f"{gateway_list}\n\n"
            "For each gateway, look at the diamond shape in the diagrams and extract:\n"
            "  - id: exactly as listed above\n"
            "  - question: the decision question text on the diamond\n"
            "  - outcomes: list of branch labels in the SAME ORDER as the arrows leave the diamond\n\n"
            "Return ONLY a JSON array (no object wrapper):\n"
            '[{"id": "step_N", "question": "...", "outcomes": ["...", "..."]}, ...]\n\n'
            "Include every gateway. If labels are not visible, use [\"Yes\", \"No\"] as defaults."
        ),
    })

    response = client.messages.create(
        model=settings.effective_model,
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
    )

    if not response.content:
        return []

    raw_text = response.content[0].text
    cleaned = re.sub(r"```(?:json)?", "", raw_text).strip()
    start = cleaned.find("[")
    if start == -1:
        return []
    return json.loads(cleaned[start:])


async def _call_claude_single(
    client: anthropic.Anthropic,
    filename: str,
    image_bytes: bytes,
    process_instructions: Optional[str] = None,
) -> tuple[dict, list[str]]:
    """Analyse a single PNG. Returns (process_data, warnings). confidence key left in process_data."""
    warnings: list[str] = []
    media_type = _detect_media_type(image_bytes, filename)

    instruction_block = ""
    if process_instructions and process_instructions.strip():
        instruction_block = (
            f"\n\nProcess instructions from the user:\n{process_instructions.strip()}\n"
            "Apply these instructions when classifying subprocesses: use <callActivity> for child cases "
            "and <subProcess> for inline subprocesses as specified."
        )

    try:
        response = client.messages.create(
            model=settings.effective_model,
            max_tokens=8096,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": _to_base64(image_bytes),
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                f"Analyse this process flow diagram ({filename}) "
                                f"and return the structured JSON as instructed.{instruction_block}"
                            ),
                        },
                    ],
                }
            ],
        )

        raw_text = response.content[0].text
        process_data = _extract_json(raw_text)
        _validate_process_data(process_data)
        return process_data, warnings

    except json.JSONDecodeError as exc:
        warnings.append(f"{filename}: Claude returned invalid JSON — using fallback. ({exc})")
        return _empty_process(), warnings
    except ValueError as exc:
        warnings.append(f"{filename}: Validation failed — {exc}. Using fallback.")
        return _empty_process(), warnings
    except anthropic.APIError as exc:
        # Re-raise API errors (SSL failures, auth errors, Zscaler interception) —
        # do NOT fall back silently or the caller gets a useless empty BPMN.
        log.error("Claude API error for %s: %s", filename, exc)
        raise


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_process_data(data: dict) -> None:
    # Fill in optional keys with empty defaults rather than failing
    data.setdefault("data_entities", [])
    data.setdefault("integrations", [])
    data.setdefault("decisions", [])

    required_keys = {"process_name", "lanes", "steps"}
    missing = required_keys - data.keys()
    if missing:
        raise ValueError(f"Missing keys in Claude response: {missing}")
    if not isinstance(data["steps"], list) or len(data["steps"]) == 0:
        raise ValueError("steps must be a non-empty list.")


def _detect_media_type(image_bytes: bytes, filename: str) -> str:
    """Detect image media type from magic bytes, fall back to filename extension."""
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if image_bytes[:4] == b"GIF8":
        return "image/gif"
    if image_bytes[:4] in (b"RIFF",) and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    # Fall back to extension
    ext = filename.lower().rsplit(".", 1)[-1]
    return {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(ext, "image/png")
