# Architecture

## Overview

```
Browser (React)
    │
    │  multipart/form-data  (PNGs, optional xlsx, optional branding)
    ▼
FastAPI Backend
    │
    ├─► Claude API (claude-sonnet-4-6)
    │       PNG vision analysis → structured JSON
    │
    ├─► bpmn_generator      → process.bpmn
    ├─► ddl_generator       → schema.sql
    ├─► openapi_generator   → api-spec.yaml
    └─► docx_generator      → bpin.docx  (optional)
    │
    │  SSE stream — confidence cards appear per image, then artefact step events
    ▼
Browser — confidence cards appear live, download buttons on complete
```

## nginx config (SSE requirement)

Add `proxy_buffering off` to the location block so SSE events are not held in nginx's buffer:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 300s;
    proxy_buffering off;          # required for SSE
    proxy_cache off;
}
```

## Data Flow

1. User uploads PNG(s) + optional xlsx + optional branding via the UI.
2. Frontend POSTs to `POST /api/generate`.
3. Backend sends each PNG to Claude with a structured prompt.
4. Claude returns a JSON description of the process: steps, roles, decisions, data entities, integrations.
5. Generators consume the structured JSON to produce each artefact.
6. If a Pega xlsx is provided, `ddl_generator` runs in delta mode — only emitting tables/columns not already in the Pega model.
7. If branding is provided, the BPIN `.docx` applies org name, colour, and logo.
8. Backend returns all files as a zip or individually via download endpoints.

## Pega Blueprint — Import Order

The three artefacts must be imported into Blueprint in this order. Importing out of order will cause property resolution errors (e.g. `Properties Name not found: PolicyId`).

| Step | File | What Blueprint creates |
|------|------|------------------------|
| 1 | `schema.sql` (DDL) | Data classes and their **properties** — `PolicyId`, `Status`, `Cover`, `EffectiveDate`, `RequestType`, `NoteType` etc. |
| 2 | `process.bpmn` | Case type, stages, steps, and assignments referencing those properties |
| 3 | `api-spec.yaml` | Connect-REST connector rules and data mappings — properties must already exist from step 1 |

### Why this order matters

The `api-spec.yaml` creates **data mappings** that reference specific property names. If the DDL has not been imported first, those properties don't exist in the application and Blueprint throws a `pyMappingModel.pyProperties … Properties Name not found` error.

### Property alignment

The DDL, BPMN, and api-spec all use the same property names derived from the process context:

```
DDL column (snake_case)  →  Pega property (PascalCase)  →  api-spec field (camelCase)
policy_id                →  PolicyId                     →  policyId
status                   →  Status                       →  status
cover                    →  Cover                        →  cover
effective_date           →  EffectiveDate                →  effectiveDate
request_type             →  RequestType                  →  requestType
reason                   →  Reason                       →  reason
note_type                →  NoteType                     →  noteType
created_by               →  CreatedBy                    →  createdBy
```

---

## Appendix — Known Issues & Fixes

### Issues

#### Issue 1 — Blueprint Import Error: `Properties Name not found`

**Status: RESOLVED — Process Forge fix applied April 2026**

> This issue does NOT block the current workflow. Process Forge was updated so the generated `api-spec.yaml` no longer triggers Blueprint's auto-wiring behaviour. You do not need to wait for a Blueprint product fix to import into your development server.
>
> The underlying Blueprint product gap has been raised as feedback (see `docs/blueprint-feedback.md`).

---

### A1 — Blueprint Import Error: `Properties Name not found`

**Error message (as seen in croog.pegademo.com):**
```
Create new record failed:
.pyMappingModel.pyProperties(1).pyPropertiesName: Properties Name not found: Cover
.pyMappingModel.pyProperties(2).pyPropertiesName: Properties Name not found: Reason
.pyMappingModel.pyProperties(3)...
```

**What causes it:**

When Blueprint imports `api-spec.yaml` it auto-generates Connect-REST connector rules with data transforms. Those transforms try to map the JSON schema field names (e.g. `cover`, `reason`) to properties in the **case type class**. If those properties don't exist in that class, Blueprint throws this error.

There are two variants of this failure:

| Variant | Root cause |
|---------|-----------|
| Wrong import order | `api-spec.yaml` imported before `schema.sql` — properties haven't been created yet |
| Class mismatch | DDL correctly created `Cover` and `Reason` in `Data-Policy`, but Blueprint's auto-generated transform looks in the **case type** class, not the data class |

**Why this kept happening even with the correct import order:**

The deeper issue is that our `api-spec.yaml` was originally built as if it were a Pega data model spec — property names chosen to match what we wanted inside Pega. An OpenAPI spec used as a connector should describe what the **external system returns**, not what Pega stores internally. Blueprint's auto-wiring is a feature that only works when the spec author knows the target app's property names in advance.

**Would this have been caught in Blueprint before hitting the dev server?**

It should have been — Blueprint holds all three artefacts simultaneously and could cross-check connector schema fields against the data model before export. It did not. Blueprint validated each artefact in isolation and exported a package that appeared valid. The error only surfaced on the development server. This is a Blueprint product gap raised as formal feedback in `docs/blueprint-feedback.md`.

**Fix applied to Process Forge (April 2026) — `openapi_generator.py`:**

Added `additionalProperties: true` to every schema and removed all property-level `required` constraints. This is the correct long-term pattern for AI-generated connector specs targeting unknown Pega apps — it tells Blueprint to create flexible connector data pages without enforcing specific property mappings. The connector imports cleanly; data transforms are wired manually in Pega Studio.

Before (caused error):
```yaml
PolicyCoverRequest:
  type: object
  properties:
    cover:
      type: string
    reason:
      type: string
  required: [cover]        # ← Blueprint tries to find 'Cover' in case class → fails
```

After (fixed):
```yaml
PolicyCoverRequest:
  type: object
  additionalProperties: true   # ← Blueprint creates a flexible data page, no forced mapping
  properties:
    cover:
      type: string             # ← documentation only, not enforced
    reason:
      type: string
```

**After import — what to do manually in Pega Studio:**

1. Open the generated Connect-REST rule for each system (e.g. Apollo, Cyclops)
2. In the **Request** tab, map case/data class properties to the JSON fields
3. In the **Response** tab, map JSON response fields back to the appropriate data class
4. The DDL-created `Data-Policy` class contains `Cover`, `Reason`, `EffectiveDate` etc. — use these as the source/target

---

## Claude Prompt Strategy

Each PNG is sent as a base64-encoded image with a system prompt instructing Claude to return a structured JSON object with the following schema:

```json
{
  "process_name": "string",
  "lanes": ["string"],
  "steps": [
    {
      "id": "string",
      "type": "task | gateway | event",
      "name": "string",
      "lane": "string",
      "sequence": ["next_step_id"]
    }
  ],
  "data_entities": ["string"],
  "integrations": ["string"],
  "decisions": [
    {
      "id": "string",
      "question": "string",
      "outcomes": ["string"]
    }
  ]
}
```
