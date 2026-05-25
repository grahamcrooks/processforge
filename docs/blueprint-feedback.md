# Pega Blueprint — Product Feedback
**From:** Bupa HI Architecture Team  
**Context:** Testing Blueprint with AI-generated artefacts (BPMN, DDL, OpenAPI spec) via Process Forge  
**Date:** April 2026

---

## Issue 1 — OpenAPI Import: cryptic error message with HTML-encoded text

**What happened:**  
When importing an `api-spec.yaml` that contained schema properties not yet present in the target application, Blueprint displayed this error in a browser dialog:

```
Create new record failed:
.pyMappingModel.pyProperties&#40;1&#41;.pyPropertiesName: Properties Name not found: Cover
.pyMappingModel.pyProperties&#40;2&#41;.pyPropertiesName: Properties Name not found: Reason
```

**Problems:**
1. The error contains raw HTML entities (`&#40;` = `(`, `&#41;` = `)`) — these should be decoded before display
2. The internal Pega path (`.pyMappingModel.pyProperties(1).pyPropertiesName`) is exposed to the user with no translation into plain language
3. The error gives no guidance on what to do next

**Suggested improvement:**  
Replace with a plain-language message that identifies the file, the cause, and the resolution path. For example:

> *"api-spec.yaml import could not complete — 2 properties referenced in the connector mappings do not exist in this application: **Cover**, **Reason**. To resolve: (a) import the DDL first to create these properties, or (b) create them manually in the data class before retrying."*

---

## Issue 2 — No enforced or guided import order for multi-artefact Blueprints

**What happened:**  
Blueprint accepts BPMN, DDL, and OpenAPI spec as separate imports with no enforced ordering or dependency check. Importing the OpenAPI spec before the DDL causes the connector import to fail because the properties the connector maps to don't exist yet.

The correct order is:
1. DDL (`schema.sql`) → creates data classes and properties
2. BPMN (`process.bpmn`) → creates case type referencing those properties  
3. OpenAPI spec (`api-spec.yaml`) → creates connectors that map to those properties

**Problems:**
1. The UI does not communicate this dependency
2. There is no pre-flight validation that checks whether referenced properties exist before attempting the import
3. Importing out of order results in a cryptic failure (see Issue 1) with no rollback guidance

**Suggested improvement:**  
- When importing an OpenAPI spec, run a pre-flight check: scan the schemas for property names and verify they exist in the application before starting the import
- If properties are missing, present a clear list with options: *"Create missing properties automatically"*, *"Import DDL first"*, or *"Continue anyway (manual wiring required)"*
- Consider a **"Import Bundle"** flow that accepts all three artefacts together and enforces the correct order automatically

---

## Issue 3 — OpenAPI schema auto-wiring assumes case class ownership of connector properties

**What happened:**  
Blueprint's OpenAPI importer auto-generates data transforms that attempt to map JSON schema fields directly to properties in the **case type class**. This works only if the spec author knows which properties already exist in the target case class and names the JSON fields to match exactly.

For AI-generated or third-party OpenAPI specs, the schema field names represent the **external system's data shape**, not Pega's internal data model. These are different things and should not be auto-mapped without confirmation.

**Problems:**
1. Auto-wiring to the case class is a hidden assumption that fails silently with a cryptic error
2. There is no way to tell Blueprint *"these schemas describe external API shapes — don't auto-wire them to case properties"* without using `additionalProperties: true` as an undocumented workaround
3. The workaround (`additionalProperties: true`) disables schema validation that would otherwise be useful

**Suggested improvement:**  
- During OpenAPI import, present a **mapping review screen** that shows proposed property mappings and lets the user confirm, adjust, or skip each one before committing
- Add an explicit import option: *"Create connector data pages only (no auto data transforms)"* — useful for AI-generated specs and third-party APIs where field names don't match the Pega data model
- Document `additionalProperties: true` as the supported pattern for this use case, rather than leaving it as an undiscovered workaround

---

## Issue 4 — Blueprint does not validate cross-artefact dependencies before export

**What happened:**  
Blueprint accepted all three artefacts (DDL, BPMN, OpenAPI spec) without any warnings. The package appeared complete and valid inside Blueprint. The property mismatch error only surfaced when importing into the Pega development server — at which point Blueprint's job was done and the error was Pega's to report.

**The gap:**  
Blueprint's role in the workflow is to be a **safe staging environment** — a place to catch problems before they reach a real server. The intended flow is:

```
Process Forge → Blueprint (design & validate) → Export → Import to Dev Server
```

Blueprint already holds all three artefacts simultaneously. It knows the data model (from the DDL), the case structure (from the BPMN), and the connector schema field names (from the OpenAPI spec). It has everything it needs to catch the mismatch internally — but it validated each artefact in isolation rather than checking the relationships between them.

**Specific check that was missing:**  
> *"Does every property name referenced in api-spec.yaml schema fields exist in the data model defined by schema.sql?"*

If Blueprint had run this check at export time, the error would have been caught inside Blueprint with a clear resolution path, rather than surfacing as a cryptic failure on the development server.

**Suggested improvement:**  
Add a **cross-artefact validation step** at export time that checks:
- All OpenAPI schema field names resolve to properties in the defined data model
- All BPMN data object references resolve to defined data classes
- All case property references in BPMN steps have a matching DDL column or existing Pega property

Surface any failures as blocking warnings inside Blueprint before the package is exported, not after it reaches a server.

---

## Summary

| # | Issue | Severity | Type |
|---|-------|----------|------|
| 1 | HTML-encoded error with internal Pega path exposed | Medium | UX / Error messaging |
| 2 | No import order guidance or dependency validation for multi-artefact Blueprints | High | UX / Workflow |
| 3 | OpenAPI auto-wiring assumes case class property ownership without user confirmation | High | Behaviour / Architecture |
| 4 | Blueprint does not validate cross-artefact dependencies before export | High | Validation / Architecture |

All four issues compound each other: Blueprint accepts artefacts individually without cross-checking them (Issue 4), exports a package that appears valid, the user imports in the wrong order (Issue 2) or with a mismatched spec (Issue 3), gets a cryptic error on the server (Issue 1), and has no path back to Blueprint to understand what went wrong.

**The core expectation that Blueprint doesn't currently meet:**  
Blueprint is positioned as the safe staging environment before a development server. Users reasonably expect that if Blueprint accepts a set of artefacts and allows export, that package will import cleanly. When errors only surface on the server, Blueprint's value as a validation gate is undermined.
