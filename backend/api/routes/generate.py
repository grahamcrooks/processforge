"""
═══════════════════════════════════════════════════════════════════════════════
PROCESS FORGE — API Routes (The Pipeline)
═══════════════════════════════════════════════════════════════════════════════

Two endpoints drive the entire application:

  POST /api/assess
    Pre-flight quality check. Sends each diagram image to Claude Vision
    for confidence scoring (7-factor rubric). Returns scores streamed
    to the frontend in real time. No artefacts generated. Fast.

  POST /api/generate
    The full pipeline. For each diagram:
      1. Claude Vision — assess confidence (uses cached score if Assess ran first)
      2. Claude Vision — extract process data (lanes, steps, flows, decisions...)
      3. bpmn_generator — produce BPMN 2.0 XML
      4. ddl_generator  — produce SQL schema
      5. openapi_generator — produce OpenAPI YAML
      6. docx_generator — produce BPIN Word doc (if requested)
      7. Package all files + extraction log for download

Both endpoints use Server-Sent Events (SSE) streaming — the frontend receives
live updates as each step completes rather than waiting for the full response.
This is why the progress tracker and log update in real time during generation.
═══════════════════════════════════════════════════════════════════════════════
"""
import json
import logging
import re
import datetime
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from typing import Optional

logger = logging.getLogger(__name__)

from api.models.schemas import GenerateResponse, ImageConfidence
from services.claude_service import analyse_diagrams_stream, assess_images_stream
from services.bpmn_generator import generate_bpmn
from services.ddl_generator import generate_ddl
from services.openapi_generator import generate_openapi
from services.docx_generator import generate_bpin
from utils.file_utils import encode_file

router = APIRouter(prefix="/api", tags=["generate"])


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _file_slug(process_name: str) -> str:
    """Convert process name to a safe lowercase hyphenated filename stem (max 60 chars)."""
    return re.sub(r"[^a-z0-9]+", "-", process_name.lower()).strip("-")[:60]


@router.post("/assess")
async def assess(
    diagrams: list[UploadFile] = File(..., description="One or more PNG process flow diagrams"),
):
    """Pre-flight quality assessment — confidence scores only, no artefact generation."""
    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    for f in diagrams:
        ext = ("." + f.filename.rsplit(".", 1)[-1].lower()) if f.filename and "." in f.filename else ""
        is_image = (f.content_type and f.content_type.startswith("image/")) or ext in image_exts
        if not is_image:
            raise HTTPException(status_code=400, detail=f"{f.filename} is not an image file.")

    diagram_bytes = [(f.filename, await f.read()) for f in diagrams]

    async def event_stream():
        try:
            async for event in assess_images_stream(diagram_bytes):
                if event["type"] == "confidence":
                    yield _sse({"type": "confidence", "data": event["data"]})
                elif event["type"] == "ref_map":
                    yield _sse({"type": "ref_map", "data": event["data"]})
            yield _sse({"type": "complete"})
        except Exception as exc:
            logger.exception("Error in assess stream")
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/generate-bpmn")
async def generate_bpmn_artefacts(
    diagrams: list[UploadFile] = File(..., description="One or more PNG process flow diagrams"),
    process_instructions: Optional[str] = Form(None),
):
    """BPMN Generation mode — generates one Blueprint-format BPMN per uploaded diagram."""
    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    for f in diagrams:
        ext = ("." + f.filename.rsplit(".", 1)[-1].lower()) if f.filename and "." in f.filename else ""
        is_image = (f.content_type and f.content_type.startswith("image/")) or ext in image_exts
        if not is_image:
            raise HTTPException(status_code=400, detail=f"{f.filename} is not an image file.")

    diagram_bytes = [(f.filename, await f.read()) for f in diagrams]

    async def event_stream():
        try:
            files = []

            yield _sse({"type": "step", "key": "claude"})

            for i, (filename, img_bytes) in enumerate(diagram_bytes):
                process_data = None
                async for event in analyse_diagrams_stream([(filename, img_bytes)], process_instructions, None):
                    if event["type"] == "image_start":
                        yield _sse({"type": "image_start", "filename": event["filename"], "tiling": event["tiling"]})
                    elif event["type"] == "done":
                        process_data = event["process_data"]
                    # confidence events deliberately suppressed — not shown in BPMN mode

                if not process_data:
                    yield _sse({"type": "detail", "message": f"  ↳ Warning: could not extract process data from {filename}"})
                    continue

                slug        = _file_slug(process_data.get("process_name", filename.rsplit(".", 1)[0]))
                steps_count = len(process_data.get("steps", []))
                lanes_count = len(process_data.get("lanes", []))
                entities    = process_data.get("data_entities", [])
                integrations = process_data.get("integrations", [])

                # BPMN
                yield _sse({"type": "step", "key": "bpmn"})
                files.append(encode_file(f"{slug}.bpmn", generate_bpmn(process_data), "application/xml"))
                yield _sse({"type": "detail", "message":
                    f"  ↳ {slug}.bpmn — {steps_count} steps · {lanes_count} lanes"})

                # DDL
                yield _sse({"type": "step", "key": "ddl"})
                files.append(encode_file(f"{slug}-schema.sql", generate_ddl(process_data, None), "text/plain"))
                yield _sse({"type": "detail", "message":
                    f"  ↳ {slug}-schema.sql — {len(entities)} {'entity' if len(entities) == 1 else 'entities'}"})

                # OpenAPI
                yield _sse({"type": "step", "key": "openapi"})
                files.append(encode_file(f"{slug}-api-spec.yaml", generate_openapi(process_data), "application/x-yaml"))
                yield _sse({"type": "detail", "message":
                    f"  ↳ {slug}-api-spec.yaml — {len(integrations)} integration endpoint{'s' if len(integrations) != 1 else ''}"})

            yield _sse({"type": "step", "key": "done"})
            bpmn_count = sum(1 for f in files if f.get("filename", "").endswith(".bpmn"))
            yield _sse({"type": "detail", "message":
                f"Packaged {len(files)} artefact{'s' if len(files) != 1 else ''} ({bpmn_count} BPMN{'s' if bpmn_count != 1 else ''})"})

            from api.models.schemas import GenerateResponse
            response = GenerateResponse(files=files, warnings=[], confidence_scores=[])
            yield _sse({"type": "complete", "data": response.model_dump()})

        except Exception as exc:
            logger.exception("Error in generate-bpmn stream")
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/generate")
async def generate(
    diagrams: list[UploadFile] = File(..., description="One or more PNG process flow diagrams"),
    pega_model: Optional[UploadFile] = File(None, description="Optional Pega data model .xlsx"),
    generate_bpin_doc: str = Form("false"),
    branding_json: Optional[str] = Form(None),
    process_instructions: Optional[str] = Form(None),
    cached_confidence_json: Optional[str] = Form(None, description="JSON map of filename→confidence from prior Assess run"),
):
    want_bpin = generate_bpin_doc.lower() in ("true", "1", "yes", "on")

    # Validate diagram types
    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    for f in diagrams:
        ext = ("." + f.filename.rsplit(".", 1)[-1].lower()) if f.filename and "." in f.filename else ""
        is_image = (f.content_type and f.content_type.startswith("image/")) or ext in image_exts
        if not is_image:
            raise HTTPException(status_code=400, detail=f"{f.filename} is not an image file.")

    branding = None
    if branding_json:
        try:
            from api.models.schemas import BrandingConfig
            branding = BrandingConfig(**json.loads(branding_json))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid branding JSON.")

    diagram_bytes = [(f.filename, await f.read()) for f in diagrams]
    pega_bytes = await pega_model.read() if pega_model else None

    # Parse cached confidence scores from prior Assess run (saves one API call per image)
    cached_confidence: Optional[dict] = None
    if cached_confidence_json:
        try:
            cached_confidence = json.loads(cached_confidence_json)
            logger.info("Using cached confidence for %d image(s)", len(cached_confidence))
        except Exception:
            logger.warning("Could not parse cached_confidence_json — will re-assess")

    async def event_stream():
        try:
            process_data = None
            all_confidence: list[dict] = []
            all_warnings: list[str] = []

            # ── Stage 1: per-image analysis ───────────────────────────────
            yield _sse({"type": "step", "key": "claude"})

            async for event in analyse_diagrams_stream(diagram_bytes, process_instructions, cached_confidence):
                if event["type"] == "image_start":
                    yield _sse({"type": "image_start",
                                "filename": event["filename"],
                                "tiling": event["tiling"]})
                elif event["type"] == "image":
                    all_confidence.append(event["confidence"])
                    all_warnings.extend(event.get("warnings", []))
                    yield _sse({"type": "confidence", "data": event["confidence"]})
                elif event["type"] == "done":
                    process_data = event["process_data"]

            # ── Stage 2: artefact generation ──────────────────────────────
            files = []
            slug          = _file_slug(process_data.get("process_name", "process"))
            all_steps     = process_data.get("steps", [])
            all_lanes     = process_data.get("lanes", [])
            all_decisions = process_data.get("decisions", [])
            all_entities  = process_data.get("data_entities", [])
            all_integ     = process_data.get("integrations", [])
            subprocs      = [s for s in all_steps if s.get("type") == "subprocess"]
            child_cases   = [s for s in subprocs if s.get("subtype") == "child_case"]
            gateways      = [s for s in all_steps if s.get("type") == "gateway"]

            yield _sse({"type": "step", "key": "bpmn"})
            files.append(encode_file(
                f"{slug}.bpmn", generate_bpmn(process_data), "application/xml"
            ))
            yield _sse({"type": "detail", "message":
                f"BPMN written — {len(all_steps)} steps · {len(all_lanes)} lanes · "
                f"{len(gateways)} gateways · {len(all_decisions)} decisions · "
                f"{len(subprocs)} subprocesses ({len(child_cases)} child cases)"
            })

            yield _sse({"type": "step", "key": "ddl"})
            files.append(encode_file(
                f"{slug}-schema.sql", generate_ddl(process_data, pega_bytes), "text/plain"
            ))
            yield _sse({"type": "detail", "message":
                f"DDL written — {len(all_entities)} data {'entity' if len(all_entities) == 1 else 'entities'} → schema tables"
                + (f" · {len(all_integ)} integration{'s' if len(all_integ) != 1 else ''} noted" if all_integ else "")
            })

            yield _sse({"type": "step", "key": "openapi"})
            files.append(encode_file(
                f"{slug}-api-spec.yaml", generate_openapi(process_data), "application/x-yaml"
            ))
            yield _sse({"type": "detail", "message":
                f"OpenAPI spec written — {len(all_integ)} integration endpoint{'s' if len(all_integ) != 1 else ''}"
                + (f" · {len(all_entities)} schema component{'s' if len(all_entities) != 1 else ''}" if all_entities else "")
            })

            if want_bpin:
                yield _sse({"type": "step", "key": "bpin"})
                files.append(encode_file(
                    "process-analysis-summary.docx",
                    generate_bpin(process_data, branding),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ))
                yield _sse({"type": "detail", "message":
                    f"BPIN document written — process analysis for {process_data.get('process_name', 'Unknown Process')}"
                })

            # ── Stage 3: extraction log ───────────────────────────────────
            yield _sse({"type": "step", "key": "done"})

            typed_scores = []
            for c in all_confidence:
                try:
                    typed_scores.append(ImageConfidence(**c))
                except Exception:
                    logger.warning("Could not build ImageConfidence from: %s", c)

            steps = process_data.get("steps", [])
            lanes = process_data.get("lanes", [])
            decisions = process_data.get("decisions", [])
            gateways = [s for s in steps if s.get("type") == "gateway"]

            subprocesses = [s for s in steps if s.get("type") == "subprocess"]

            extraction_log = {
                "run_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "images_processed": [
                    {
                        "filename": c.filename,
                        "dimensions": f"{c.image_width}×{c.image_height}px",
                        "tiled": c.tiled,
                        "tile_count": c.tile_count,
                        "tiling_note": (
                            f"Image split into {c.tile_count} overlapping tiles for extraction"
                            if c.tiled else "Sent as single image (no tiling needed)"
                        ),
                        "confidence_score": c.score,
                        "readability": c.readability,
                        "confidence_notes": c.notes,
                        "unclear_elements": c.unclear_elements,
                        "steps_extracted": c.steps_extracted,
                        "lanes_identified": c.lanes_identified,
                        "gateways_found": c.gateways_found,
                        "decisions_extracted": c.decisions_extracted,
                        "warnings": c.warnings,
                    }
                    for c in typed_scores
                ],
                "merged_process": {
                    "process_name": process_data.get("process_name", "Unknown"),
                    "lanes": lanes,
                    "total_steps": len(steps),
                    "total_lanes": len(lanes),
                    "total_gateways": len(gateways),
                    "total_decisions": len(decisions),
                    "steps_by_type": {
                        "task":       sum(1 for s in steps if s.get("type") == "task"),
                        "gateway":    len(gateways),
                        "event":      sum(1 for s in steps if s.get("type") == "event"),
                        "subprocess": len(subprocesses),
                    },
                    "step_names": [
                        f"{s.get('name', '')} ({s['source_ref']})" if s.get('source_ref') else s.get('name', '')
                        for s in steps
                    ],
                    "gateway_decisions": [
                        {"gateway": d.get("question", ""), "outcomes": d.get("outcomes", [])}
                        for d in decisions
                    ],
                    "invoked_processes": {
                        "child_cases": [
                            {
                                "name": s.get("name", ""),
                                "source_ref": s.get("source_ref"),
                                "lane": s.get("lane", ""),
                                "bpmn_element": "callActivity",
                            }
                            for s in subprocesses if s.get("subtype") == "child_case"
                        ],
                        "inline_subprocesses": [
                            {
                                "name": s.get("name", ""),
                                "source_ref": s.get("source_ref"),
                                "lane": s.get("lane", ""),
                                "bpmn_element": "subProcess",
                            }
                            for s in subprocesses if s.get("subtype") != "child_case"
                        ],
                    },
                    "data_entities": process_data.get("data_entities", []),
                    "integrations": process_data.get("integrations", []),
                },
                "artefacts_generated": [f.filename for f in files],
                "warnings": all_warnings,
            }
            files.append(encode_file(
                "extraction-log.json",
                json.dumps(extraction_log, indent=2).encode(),
                "application/json",
            ))

            # ── Complete ──────────────────────────────────────────────────
            response = GenerateResponse(
                files=files,
                warnings=all_warnings,
                confidence_scores=typed_scores,
            )
            yield _sse({"type": "complete", "data": response.model_dump()})

        except Exception as exc:
            logger.exception("Error in generate stream")
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
