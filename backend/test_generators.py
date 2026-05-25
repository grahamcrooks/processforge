"""
Stage 4 smoke-test — exercises all four generators with rich sample data.
Writes output files to ./test_output/ so you can inspect them.

Usage:
    python test_generators.py
"""
import asyncio
import json
import os
import pathlib

# Rich sample process data (simulates what Claude would return for a real diagram)
SAMPLE_PROCESS = {
    "process_name": "Bupa Health Insurance Claims Processing",
    "lanes": ["Member", "Claims Team", "Medical Review", "Finance"],
    "steps": [
        {"id": "step_1", "type": "event",   "name": "Start",                  "lane": "Member",         "sequence": ["step_2"]},
        {"id": "step_2", "type": "task",    "name": "Submit Claim",            "lane": "Member",         "sequence": ["step_3"]},
        {"id": "step_3", "type": "task",    "name": "Validate Claim Form",     "lane": "Claims Team",    "sequence": ["step_4"]},
        {"id": "step_4", "type": "gateway", "name": "Is Claim Valid?",         "lane": "Claims Team",    "sequence": ["step_5", "step_9"]},
        {"id": "step_5", "type": "task",    "name": "Assess Claim",            "lane": "Claims Team",    "sequence": ["step_6"]},
        {"id": "step_6", "type": "gateway", "name": "Medical Review Required?","lane": "Claims Team",    "sequence": ["step_7", "step_8"]},
        {"id": "step_7", "type": "task",    "name": "Medical Review",          "lane": "Medical Review", "sequence": ["step_8"]},
        {"id": "step_8", "type": "task",    "name": "Approve / Decline",       "lane": "Claims Team",    "sequence": ["step_10"]},
        {"id": "step_9", "type": "task",    "name": "Return to Member",        "lane": "Claims Team",    "sequence": ["step_11"]},
        {"id": "step_10","type": "task",    "name": "Process Payment",         "lane": "Finance",        "sequence": ["step_11"]},
        {"id": "step_11","type": "event",   "name": "End",                     "lane": "Member",         "sequence": []},
    ],
    "data_entities": ["Claim", "Member", "Policy", "Provider", "Payment"],
    "integrations": ["Core Banking API", "Medicare Eligibility Service", "Provider Registry"],
    "decisions": [
        {"id": "step_4", "question": "Is Claim Valid?",          "outcomes": ["Yes — proceed", "No — return to member"]},
        {"id": "step_6", "question": "Medical Review Required?", "outcomes": ["Yes", "No"]},
    ],
}


def test_bpmn():
    from services.bpmn_generator import generate_bpmn
    bpmn = generate_bpmn(SAMPLE_PROCESS)
    assert b"<?xml" in bpmn
    assert b"proc_1" in bpmn                          # collaboration structure
    assert b"collaboration" in bpmn                   # multi-lane → collaboration
    assert b"participant" in bpmn
    assert b"Claims Processing" in bpmn
    assert b"sequenceFlow" in bpmn
    assert b"exclusiveGateway" in bpmn                # gateways present
    assert b"Submit Claim" in bpmn                    # real step names used
    assert b"callActivity" not in bpmn or b"subprocess" not in bpmn  # either fine
    print(f"  BPMN   OK  ({len(bpmn):,} bytes)")
    return bpmn


def test_ddl():
    from services.ddl_generator import generate_ddl
    # Without Pega model
    ddl = generate_ddl(SAMPLE_PROCESS, None)
    assert b"CREATE TABLE" in ddl
    assert b"claim" in ddl
    assert b"member" in ddl
    print(f"  DDL    OK  ({len(ddl):,} bytes) — full mode")

    # Delta mode with fake xlsx (no existing tables to parse = empty set = all tables written)
    import io
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Class Name", "Property Name"])
        ws.append(["Claim", "claimId"])   # Claim already exists
        buf = io.BytesIO()
        wb.save(buf)
        pega_bytes = buf.getvalue()
        ddl_delta = generate_ddl(SAMPLE_PROCESS, pega_bytes)
        assert b"Skipped" in ddl_delta
        print(f"  DDL    OK  ({len(ddl_delta):,} bytes) — delta mode")
    except ImportError:
        print("  DDL    SKIP delta mode (openpyxl not available)")

    return ddl


def test_openapi():
    from services.openapi_generator import generate_openapi
    yaml_bytes = generate_openapi(SAMPLE_PROCESS)
    assert b"openapi:" in yaml_bytes
    assert b"Claims Processing" in yaml_bytes
    assert b"/claim" in yaml_bytes
    print(f"  OpenAPI OK ({len(yaml_bytes):,} bytes)")
    return yaml_bytes


def test_docx():
    from services.docx_generator import generate_bpin
    from api.models.schemas import BrandingConfig

    branding = BrandingConfig(
        org_name="Bupa Australia",
        primary_colour="#0057B8",
        logo_base64=None,
    )
    docx_bytes = generate_bpin(SAMPLE_PROCESS, branding)
    # DOCX files start with PK (zip magic bytes)
    assert docx_bytes[:2] == b"PK"
    print(f"  BPIN   OK  ({len(docx_bytes):,} bytes)")
    return docx_bytes


def main():
    out_dir = pathlib.Path("test_output")
    out_dir.mkdir(exist_ok=True)

    print("Running generator tests...\n")

    bpmn = test_bpmn()
    (out_dir / "process.bpmn").write_bytes(bpmn)

    ddl = test_ddl()
    (out_dir / "schema.sql").write_bytes(ddl)

    yaml_bytes = test_openapi()
    (out_dir / "api-spec.yaml").write_bytes(yaml_bytes)

    docx_bytes = test_docx()
    (out_dir / "bpin.docx").write_bytes(docx_bytes)

    print(f"\nAll generators passed. Output written to ./{out_dir}/")
    print("  process.bpmn  — open in any BPMN viewer")
    print("  schema.sql    — inspect DDL")
    print("  api-spec.yaml — paste into editor.swagger.io")
    print("  bpin.docx     — open in Word / LibreOffice")


if __name__ == "__main__":
    main()
