# Process Forge — Presentation Notes

---

## 1. What is Process Forge?

Process Forge takes a photograph or export of a hand-drawn or Visio-style business process diagram
and automatically generates production-ready Pega Blueprint artefacts:

- **BPMN 2.0 XML** — importable directly into Pega Blueprint
- **SQL schema (DDL)** — database tables derived from data entities in the diagram
- **OpenAPI YAML spec** — API endpoints for every external integration identified
- **BPIN Word document** — process analysis summary for stakeholders

The entire pipeline is driven by **Claude Vision** — Anthropic's multimodal AI — which reads the
diagram image the same way a human analyst would, but in seconds.

---

## 2. The Technology Stack

| Layer | Technology | Why |
|---|---|---|
| Frontend | React + Vite | Fast, component-based UI with live streaming updates |
| Backend | Python + FastAPI | Async streaming, lightweight, easy to follow |
| AI Engine | Claude Vision (claude-sonnet-4-6) | Multimodal — reads images AND reasons about structure |
| Image processing | Pillow (PIL) | Tile large diagrams before sending to Claude |
| BPMN generation | Pure Python | No dependency on external BPMN libraries |
| Dev/mock mode | Fixture JSON files | Demo without API credits |

---

## 3. Claude Vision — The Core Intelligence

### What is Claude Vision?

Claude Vision is Anthropic's multimodal AI model. Unlike standard language models that only process
text, Claude Vision accepts **images as input** and can reason about what it sees — reading labels,
understanding spatial relationships, tracing flows, and interpreting visual structure.

In Process Forge, we send Claude a PNG of a process diagram and ask it to return structured JSON.
Claude reads the image exactly as a senior business analyst would:

- Identifies every swimlane (who does what)
- Reads every task, gateway and event label verbatim
- Traces sequence arrows to understand flow order
- Identifies decision points and their branch outcomes
- Spots external system integrations
- Recognises sub-processes and whether they are child cases or inline

### Why Claude Vision specifically?

- **Instruction-following is exceptional** — the SYSTEM_PROMPT gives Claude precise rules and it
  follows them. The output JSON is consistently structured and machine-parseable.
- **Handles ambiguity intelligently** — if a label is partially obscured, Claude makes a reasoned
  inference and flags it in the confidence notes rather than silently guessing
- **Self-reporting confidence** — Claude tells us how confident it is in its extraction and which
  elements were unclear. No other OCR or vision tool does this out of the box.
- **Multi-image reasoning** — Claude can receive 4-6 tiles of a large diagram and merge them into
  one coherent process, deduplicating steps at the join points

### The Confidence Scoring System

Before generating artefacts, Process Forge asks Claude to score each image across **7 factors**:

1. Image resolution & sharpness
2. Step / task label legibility
3. Flow arrow clarity
4. Swimlane structure
5. Gateway & decision legibility
6. Process completeness (no cut-off edges)
7. Structural density (overlap / crowding)

The score is an average of all 7 — **not just "can you see it?"** but **"can you reliably
extract it?"** This is the key distinction from a simple image quality check.

Scores below 55% trigger a warning recommending the source image be improved before generating.

---

## 4. The Pipeline — Step by Step

```
User uploads PNG diagram(s)
        │
        ▼
┌─────────────────────────────────┐
│  preprocessor.py                │
│  • Measure image dimensions     │
│  • Score readability (PIL)      │
│  • If tall or low-quality:      │
│    split into overlapping tiles │
│    + enhance contrast/sharpness │
└────────────┬────────────────────┘
             │ image bytes (tiled or whole)
             ▼
┌─────────────────────────────────┐
│  claude_service.py              │
│  PASS 1 — Confidence Assessment │
│  • Send image to Claude Vision  │
│  • Score across 7 factors       │
│  • Return score + unclear items │
└────────────┬────────────────────┘
             │ confidence score streamed to UI
             ▼
┌─────────────────────────────────┐
│  claude_service.py              │
│  PASS 2 — Process Extraction    │
│  • Send image + SYSTEM_PROMPT   │
│  • Claude reads: lanes, steps,  │
│    gateways, decisions, flows,  │
│    data entities, integrations  │
│  • Returns structured JSON      │
└────────────┬────────────────────┘
             │ process_data JSON
             ▼
┌─────────────────────────────────────────────────────┐
│  Artefact Generators (parallel)                     │
│  bpmn_generator.py  →  BPMN 2.0 XML                │
│  ddl_generator.py   →  SQL schema (CREATE TABLE)    │
│  openapi_generator.py → OpenAPI YAML spec           │
│  docx_generator.py  →  BPIN Word document           │
└────────────┬────────────────────────────────────────┘
             │ files streamed back to browser
             ▼
        Download panel
```

---

## 5. The Tiling Innovation

**The problem:** Large or complex process diagrams can be 3,000–5,000px tall. Sending an image
that large to any vision API risks losing detail in small text and thin arrows.

**The solution (preprocessor.py):**

1. Any image taller than 1,000px is automatically split into vertical tiles of 700px each
2. Each tile **overlaps the next by 18%** (126px) — this ensures no step or arrow is cut
   off exactly at a tile boundary
3. Each tile is **enhanced** — contrast ×1.4, sharpness ×1.8, brightness ×1.05
4. All tiles are sent to Claude **in a single API call** with positional context:
   *"Tile 2 of 4 from 'diagram.png', rows 574–1274px of the original, overlaps 126px with Tile 1"*
5. Claude deduplicates steps in the overlap zones and returns **one unified process JSON**

**Why this matters for the demo:**
> "A real enterprise process diagram might span 20 swimlanes and 50 steps. Without tiling,
> the bottom third of the diagram would be unreadable. With tiling, Claude sees every label
> in every section at full resolution."

---

## 6. The SYSTEM_PROMPT — Where the Intelligence Lives

The `SYSTEM_PROMPT` in `claude_service.py` is the most important 50 lines in the application.
It tells Claude:

- **What role to play:** "You are a business process analyst specialising in BPMN 2.0"
- **Exactly what to extract:** lanes, steps, gateways, decisions, sequences, data entities, integrations
- **The precise JSON schema** to return (machine-parseable, no prose)
- **Strict rules** for edge cases:
  - Swimlane headers with multiple roles → take the first only
  - Subprocess classification → child_case (callActivity) vs inline (subProcess)
  - Step labels with reference numbers → split into source_ref + name
  - Multiple diagrams → merge into one coherent process

**Key talking point:**
> "This is prompt engineering as software engineering. The prompt is not a natural language
> request — it's a formal specification. Every rule in it was written to handle a real edge
> case we found in Bupa process diagrams."

---

## 7. Artefact Generators

Each generator takes the `process_data` JSON from Claude and produces a file:

### bpmn_generator.py
- Produces BPMN 2.0 XML matching Pega Blueprint's import structure
- One `<process>` per swimlane/participant
- `<callActivity>` for child cases (independent Pega cases)
- `<subProcess>` for inline subprocesses (same case)
- `<exclusiveGateway>` for every decision point
- Named `<sequenceFlow>` elements for every branch outcome
- Fuzzy lane matching handles minor label differences between diagrams

### ddl_generator.py
- Creates `CREATE TABLE` SQL for every data entity Claude identified
- **Delta mode:** if a Pega data model `.xlsx` export is uploaded, only generates
  tables that don't already exist — no duplicate table errors on import

### openapi_generator.py
- Generates an OpenAPI 3.0 YAML spec
- One endpoint per external integration Claude identified in the diagram
- Ready for import into Pega's Connect-REST configuration

### docx_generator.py
- Generates a BPIN (Blueprint Process Information Note) Word document
- Supports custom branding — org name, logo, primary colour
- Structured for stakeholder sign-off

---

## 8. Why Not LangChain?

| | LangChain | Process Forge approach |
|---|---|---|
| Workflow | Dynamic agent loops | Linear, predictable pipeline |
| Prompt control | Abstracted | Direct — we own every token |
| Streaming | Callback-based | Native FastAPI SSE |
| Dependencies | Dozens | FastAPI + Anthropic SDK |
| Explainability | Hard to trace | 6 files, easy to walk through |

**One-liner:** *"LangChain is great when you need its complexity. We don't — Claude Vision
does the heavy lifting and we talk to it directly."*

**Acknowledge LangChain's strengths:** RAG pipelines, multi-model routing, long-session memory.
If this app ever needed to pull in external knowledge bases, LangChain would be worth revisiting.

---

## 9. The Architecture Wizard

After running **Assess Images**, the **Reference Map** panel appears on the right side showing
all process reference numbers extracted from your diagrams. The **Wizard** tab opens by default.

### What the Wizard does

Bupa process diagrams use a dotted numbering convention (e.g. 6.2.3.1, 6.2.3.1.1) that maps
naturally to a Pega case hierarchy. The Wizard guides you through that hierarchy level-by-level
so you can classify every subprocess before generating the BPMN.

This matters because:
- A **Case Type** becomes a top-level Pega case — an independent workbasket item
- A **Child Case** becomes a `<callActivity>` in BPMN — called from the parent but resolved
  independently with its own data model
- An **Inline** subprocess becomes a `<subProcess>` — embedded within the parent case

Classifying these correctly is essential for Pega Blueprint to import the BPMN correctly.

### Step-by-step walkthrough

**Step 1 — Set starting Case Type**

Enter the top-level process reference you are working on and give it a business name:

```
Process ref:    6.2.3.1
Business name:  Change Policy Information
```

Click **Next →**

**Step 2 — Classify direct children**

The Wizard shows every subprocess one level below your starting ref.
For each one, decide:

| Option | When to use |
|---|---|
| **Case Type** | This is a standalone process that becomes its own Pega case type (e.g. 6.2.3.1.1 Change of Cover) |
| **Inline** | This step happens inside the parent case — no separate case type needed |

Click **Next →** when all children are classified. If a subprocess is missing from the list
(e.g. a cross-series ref like 6.2.2.9), type it into the **Add missing ref** field and press Enter.

**Step 3 — Drill into each Case Type**

For each item you marked as Case Type in Step 2, the Wizard drills in and shows its children.
Now classify each child as:

| Option | When to use |
|---|---|
| **Child Case** | Started from the parent but resolved independently — `<callActivity>` in BPMN |
| **Inline** | Embedded steps, no separate case — `<subProcess>` in BPMN |

Give each Child Case a business name (used as the case type ID in Pega).

**Drag to reorder:** grab the ⠿ handle on any row to drag it into the correct processing order.
This order flows through into the BPMN sequence.

**Step 4 — Review and Apply**

The Wizard generates a Process Instructions string summarising your decisions:

```
Root: 6.2.3.1 (Change Policy Information). 6.2.3.1.1 is a Case Type named Change of Cover;
6.2.3.1.2 is a Case Type named Add Person to Policy; 6.2.3.1.3 is inline
```

Click **Apply to Process Instructions** — this populates the Process Instructions field in
the Upload panel. Running the Wizard again for a second process (e.g. 6.2.3.2) **appends**
to the existing instructions rather than replacing them.

### Multiple runs

For a large process family (e.g. 6.2.3.1, 6.2.3.2, 6.2.3.3 …) run the Wizard once per
top-level Case Type, applying after each run. The instructions accumulate so Generate sees
the full hierarchy in one pass.

### Tips

- Run **Assess** first — the Wizard uses the extracted reference numbers as its source
- If a ref is missing, use **Add missing ref** (Enter or the + Add button)
- You can edit the Process Instructions field directly after applying if you need to tweak wording
- Steps without reference numbers (e.g. "View customer details") are automatically treated
  as inline — they don't appear in the Wizard

---

## 10. Demo Flow (Recommended)

1. **Start in mock mode** (`./use-mock.sh && ./start.sh`) — instant results, no API credits
2. Upload diagrams → click **Assess Images** → walk through the confidence scores and 7 factors
3. Switch to the **Wizard** tab (opens by default) → enter the root ref → classify children
4. Click **Apply to Process Instructions** → review the generated text in the Upload panel
5. Click **Generate Artefacts** → show the live log streaming → download the BPMN
6. Open `claude_service.py` → show `SYSTEM_PROMPT` — *"this is what tells Claude what to read"*
7. Open `preprocessor.py` → show `tile_image()` — *"this is how we handle large diagrams"*
8. Switch to live mode for the finale if ZScaler is resolved: `./use-live.sh && ./start.sh`

---

## 11. Anticipated Questions & Answers

**Q: How accurate is the extraction?**
A: On clear, high-resolution diagrams (score 75%+) extraction is highly accurate — labels are
verbatim, flow is correct, gateways match. On complex dense diagrams, some manual review of
the BPMN is expected. The confidence scoring system tells you upfront which diagrams need attention.

**Q: What happens with handwritten diagrams?**
A: Claude Vision can read neat handwriting but accuracy drops. The confidence score will reflect
this. Best results come from Visio, Lucidchart, or high-resolution PDF exports.

**Q: Is the data sent to Anthropic?**
A: Yes — images are sent to Anthropic's API for processing. This is the same consideration as
using any cloud AI service. For sensitive diagrams, the mock mode allows full testing without
any data leaving the building.

**Q: Could this work for non-Pega BPMN tools?**
A: The extraction is tool-agnostic — the JSON output could feed any BPMN generator.
The current generators target Pega Blueprint's import structure but the architecture
supports adding new output formats as additional generator files.

**Q: How long does it take?**
A: In live mode, typically 8–15 seconds per diagram depending on size and tiling.
The streaming UI shows progress in real time so it never feels like a black box.

---

## 12. Key Files — Quick Reference Card

| File | One line |
|---|---|
| `claude_service.py` | Sends images to Claude Vision, receives structured JSON |
| `preprocessor.py` | Tiles large images, enhances quality before Claude sees them |
| `generate.py` (routes) | The pipeline endpoint — assess, extract, generate, stream |
| `bpmn_generator.py` | Turns process JSON into Pega-ready BPMN 2.0 XML |
| `ddl_generator.py` | Turns data entities into SQL CREATE TABLE statements |
| `openapi_generator.py` | Turns integrations into OpenAPI YAML endpoints |
| `docx_generator.py` | Generates branded BPIN Word document |
| `App.jsx` | React frontend — state, API calls, streaming, layout |
| `ExtractionPanel.jsx` | Confidence scores, 7-factor rubric, assessment results |
| `preprocessor.py` | Image tiling and quality enhancement |
