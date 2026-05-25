"""
═══════════════════════════════════════════════════════════════════════════════
PROCESS FORGE — SQL Schema Generator (DDL)
═══════════════════════════════════════════════════════════════════════════════

Converts process extraction data into PostgreSQL CREATE TABLE statements for
import into Pega Blueprint.

ALIGNMENT RULE: Column names here are the snake_case equivalents of the
camelCase JSON fields in api-spec.yaml. Pega Blueprint converts snake_case
DDL columns → PascalCase properties (e.g. policy_id → PolicyId), which then
match the API connector mappings generated from the OpenAPI spec.

  DDL column      → Pega property  → api-spec JSON field
  policy_id       → PolicyId       → policyId
  request_type    → RequestType    → requestType
  effective_date  → EffectiveDate  → effectiveDate

DELTA MODE: if a Pega data model .xlsx export is uploaded, existing tables
are skipped so only net-new entities are emitted.
═══════════════════════════════════════════════════════════════════════════════
"""
import io
import re
from datetime import date
from typing import Optional

try:
    import openpyxl
    _HAS_OPENPYXL = True
except ImportError:
    _HAS_OPENPYXL = False


# ── Shared context helpers (kept in sync with openapi_generator.py) ────────────

def _to_snake(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower() or "entity"


def _is_process_ref(name: str) -> bool:
    return bool(re.match(r"^\d+\.\d+", name.strip()))


def _primary_resource(process_name: str) -> str:
    n = process_name.lower()
    if any(w in n for w in ["cover", "policy", "insurance", "enrol"]):
        return "Policy"
    if any(w in n for w in ["person", "member", "beneficiary", "dependent"]):
        return "Person"
    if any(w in n for w in ["claim", "benefit", "reimburse"]):
        return "Claim"
    if any(w in n for w in ["payment", "billing", "premium", "invoice", "refund"]):
        return "Payment"
    if any(w in n for w in ["complaint", "dispute", "escalat"]):
        return "Complaint"
    if any(w in n for w in ["cancel", "offboard", "terminat"]):
        return "Policy"
    return "Record"


def _sub_resource(process_name: str) -> str:
    n = process_name.lower()
    if "cover" in n and "change" in n:
        return "cover"
    if "cover" in n:
        return "cover"
    if "person" in n or "member" in n or "add" in n:
        return "member"
    if "address" in n or "contact" in n:
        return "contact_details"
    if "payment" in n or "billing" in n:
        return "payment"
    if "cancel" in n or "terminat" in n:
        return "status"
    if "complaint" in n:
        return "complaint"
    return "details"


def _process_verb(process_name: str) -> str:
    n = process_name.lower()
    if any(w in n for w in ["add", "create", "new", "register", "enrol", "open"]):
        return "create"
    if any(w in n for w in ["cancel", "terminat", "remove", "offboard", "close"]):
        return "cancel"
    return "update"


# ── Pega xlsx delta mode ───────────────────────────────────────────────────────

def _parse_pega_tables(pega_bytes: bytes) -> set[str]:
    if not _HAS_OPENPYXL:
        return set()
    existing: set[str] = set()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(pega_bytes), read_only=True, data_only=True)
        for sheet in wb.worksheets:
            for row in sheet.iter_rows(min_row=2, values_only=True):
                if row and row[0]:
                    existing.add(_to_snake(str(row[0])))
        wb.close()
    except Exception:
        pass
    return existing


# ── Table DDL builders ─────────────────────────────────────────────────────────

def _col(name: str, dtype: str, constraint: str = "") -> str:
    pad = max(1, 24 - len(name))
    return f"    {name}{' ' * pad}{dtype}{(' ' + constraint.strip()) if constraint else ''}"


def _main_table(res: str, sub: str, verb: str, process_name: str) -> str:
    """
    Primary record table — columns match the fields in api-spec PolicyRecord
    and the *Request schema so Blueprint can map them cleanly.
    """
    table  = _to_snake(res)           # e.g. policy
    id_col = f"{table}_id"            # e.g. policy_id  → Pega: PolicyId
    sub_col = _to_snake(sub)          # e.g. cover       → Pega: Cover

    cols = [
        _col(id_col,          "TEXT",        "PRIMARY KEY"),
        _col("status",        "TEXT",        "NOT NULL DEFAULT 'active'"),
        _col(sub_col,         "TEXT",        ""),
        _col("effective_date","DATE",        ""),
        _col("reason",        "TEXT",        ""),
    ]

    # Extra columns for person/member processes
    if res.lower() in ("person", "member"):
        cols += [
            _col("first_name",    "TEXT", ""),
            _col("last_name",     "TEXT", ""),
            _col("date_of_birth", "DATE", ""),
        ]

    # Extra columns for payment processes
    if res.lower() == "payment":
        cols += [
            _col("amount",        "NUMERIC(10,2)", ""),
            _col("frequency",     "TEXT",          ""),
            _col("payment_method","TEXT",          ""),
        ]

    # Common audit columns
    cols += [
        _col("request_type",  "TEXT",        ""),
        _col("created_at",    "TIMESTAMPTZ", "NOT NULL DEFAULT NOW()"),
        _col("updated_at",    "TIMESTAMPTZ", "NOT NULL DEFAULT NOW()"),
        _col("created_by",    "TEXT",        ""),
    ]

    col_block = ",\n".join(cols)

    return f"""\
-- ── {res.upper()} ─────────────────────────────────────────────────────────────────
-- Pega Data Class: {res}
-- Maps to api-spec schema: {res}Record, {res}{sub.capitalize()}Request
CREATE TABLE IF NOT EXISTS {table} (
{col_block}
);
CREATE INDEX IF NOT EXISTS idx_{table}_status ON {table} (status);
CREATE INDEX IF NOT EXISTS idx_{table}_effective_date ON {table} (effective_date);
"""


def _notes_table(res: str) -> str:
    """
    Process notes / audit events table.
    Matches api-spec NoteRequest / NoteResponse schemas.
    Columns: note_id, {res}_id (FK), note_type, note_text, created_by, created_at
    """
    table   = _to_snake(res)
    fk_col  = f"{table}_id"

    cols = [
        _col("note_id",    "UUID",        "PRIMARY KEY DEFAULT gen_random_uuid()"),
        _col(fk_col,       "TEXT",        f"NOT NULL REFERENCES {table}({fk_col})"),
        _col("note_type",  "TEXT",        "NOT NULL DEFAULT 'manual'"),
        _col("note_text",  "TEXT",        "NOT NULL"),
        _col("created_by", "TEXT",        ""),
        _col("created_at", "TIMESTAMPTZ", "NOT NULL DEFAULT NOW()"),
    ]
    col_block = ",\n".join(cols)

    return f"""\
-- ── {res.upper()} NOTES ───────────────────────────────────────────────────────────
-- Pega Data Class: {res}Note
-- Maps to api-spec schema: NoteRequest, NoteResponse
CREATE TABLE IF NOT EXISTS {table}_note (
{col_block}
);
CREATE INDEX IF NOT EXISTS idx_{table}_note_fk ON {table}_note ({fk_col});
"""


def _interaction_table() -> str:
    """Telephony / channel interaction log. Maps to api-spec InteractionRequest."""
    cols = [
        _col("interaction_id", "UUID",        "PRIMARY KEY DEFAULT gen_random_uuid()"),
        _col("channel",        "TEXT",        "NOT NULL"),
        _col("customer_id",    "TEXT",        ""),
        _col("agent_id",       "TEXT",        ""),
        _col("reason",         "TEXT",        ""),
        _col("status",         "TEXT",        ""),
        _col("started_at",     "TIMESTAMPTZ", "NOT NULL DEFAULT NOW()"),
        _col("ended_at",       "TIMESTAMPTZ", ""),
    ]
    col_block = ",\n".join(cols)
    return f"""\
-- ── INTERACTION ──────────────────────────────────────────────────────────────
-- Pega Data Class: Interaction
-- Maps to api-spec schema: InteractionRequest, InteractionResponse
CREATE TABLE IF NOT EXISTS interaction (
{col_block}
);
CREATE INDEX IF NOT EXISTS idx_interaction_customer ON interaction (customer_id);
"""


def _request_log_table(res: str, sub: str) -> str:
    """Self-service / portal request log. Maps to api-spec RequestResponse."""
    table  = _to_snake(res)
    id_col = f"{table}_id"
    sub_col = _to_snake(sub)

    cols = [
        _col("request_id",    "UUID",        "PRIMARY KEY DEFAULT gen_random_uuid()"),
        _col(id_col,          "TEXT",        ""),
        _col(sub_col,         "TEXT",        ""),
        _col("request_type",  "TEXT",        ""),
        _col("status",        "TEXT",        "NOT NULL DEFAULT 'received'"),
        _col("submitted_at",  "TIMESTAMPTZ", "NOT NULL DEFAULT NOW()"),
        _col("completed_at",  "TIMESTAMPTZ", ""),
        _col("submitted_by",  "TEXT",        ""),
    ]
    col_block = ",\n".join(cols)

    return f"""\
-- ── REQUEST LOG ──────────────────────────────────────────────────────────────
-- Pega Data Class: ServiceRequest
-- Maps to api-spec schema: RequestResponse
CREATE TABLE IF NOT EXISTS service_request (
{col_block}
);
CREATE INDEX IF NOT EXISTS idx_service_request_status ON service_request (status);
CREATE INDEX IF NOT EXISTS idx_service_request_policy ON service_request ({id_col});
"""


def _updated_at_trigger() -> str:
    return """\
-- ── TRIGGER — auto-update updated_at ────────────────────────────────────────
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


# ── Main entry point ───────────────────────────────────────────────────────────

def generate_ddl(process_data: dict, pega_bytes: Optional[bytes]) -> bytes:
    process_name: str       = process_data.get("process_name", "Process")
    integrations: list[str] = process_data.get("integrations", [])
    today                   = date.today().isoformat()

    # Derive process context — same logic as openapi_generator so columns align
    res    = _primary_resource(process_name)
    sub    = _sub_resource(process_name)
    verb   = _process_verb(process_name)

    # Identify which domain-specific tables we need based on integration types
    from services.openapi_generator import _system_meta, _is_process_ref as _is_ref
    systems = [i for i in integrations if not _is_ref(i)]
    domains = {_system_meta(s)[1] for s in systems}

    # Delta mode — skip tables that already exist in the Pega model export
    existing_tables: set[str] = set()
    delta_mode = bool(pega_bytes)
    if pega_bytes:
        existing_tables = _parse_pega_tables(pega_bytes)

    def _should_write(table_name: str) -> bool:
        return not delta_mode or _to_snake(table_name) not in existing_tables

    lines: list[str] = [
        "-- ================================================================",
        f"-- Blueprint DDL  —  {process_name}",
        f"-- Generated by Process Forge on {today}",
        "--",
        "-- COLUMN NAMING CONVENTION:",
        "--   snake_case columns map to PascalCase Pega properties, which",
        "--   match the camelCase JSON fields in the generated api-spec.yaml.",
        "--   e.g.  policy_id → PolicyId → policyId (api-spec)",
        "--         request_type → RequestType → requestType (api-spec)",
        "--",
    ]
    if delta_mode:
        lines.append(f"-- Mode: DELTA — skipping {len(existing_tables)} tables already in Pega model")
    lines += [
        "-- ================================================================",
        "",
        "CREATE EXTENSION IF NOT EXISTS pgcrypto;",
        "",
    ]

    # ── Primary record table ──
    table_name = _to_snake(res)
    if _should_write(table_name):
        lines.append(_main_table(res, sub, verb, process_name))
    else:
        lines.append(f"-- SKIPPED (exists): {table_name}")
        lines.append("")

    # ── Notes table ──
    notes_table = f"{table_name}_note"
    if _should_write(notes_table):
        lines.append(_notes_table(res))
    else:
        lines.append(f"-- SKIPPED (exists): {notes_table}")
        lines.append("")

    # ── Interaction table — if telephony systems present ──
    if "telephony" in domains and _should_write("interaction"):
        lines.append(_interaction_table())

    # ── Service request log — if portal/routing systems present ──
    if domains & {"portal", "routing"} and _should_write("service_request"):
        lines.append(_request_log_table(res, sub))

    # ── Trigger helper ──
    lines.append(_updated_at_trigger())

    # ── Summary comment ──
    lines += [
        "-- ================================================================",
        "-- PROPERTY ALIGNMENT SUMMARY",
        "-- The following Pega properties will be created from this DDL.",
        "-- They match the field names used in api-spec.yaml schemas:",
        "--",
        f"--   {_to_snake(res)} table → {res}Record schema",
        f"--     {table_name}_id     → {res}Id (primary key / path param)",
        f"--     status              → Status",
        f"--     {_to_snake(sub)}   → {sub.replace('_', ' ').title().replace(' ', '')}",
        f"--     effective_date      → EffectiveDate",
        f"--     request_type        → RequestType",
        f"--     reason              → Reason",
        f"--     created_by          → CreatedBy",
        "--",
        f"--   {table_name}_note table → NoteRequest / NoteResponse schema",
        f"--     note_type           → NoteType",
        f"--     note_text           → NoteText",
        f"--     created_by          → CreatedBy",
        "-- ================================================================",
        "",
    ]

    return "\n".join(lines).encode("utf-8")
