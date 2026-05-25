"""
Quick test script — runs the 4 input PNGs through the full pipeline
(Claude analysis + BPMN generation) and writes the output to
/tmp/test_output.bpmn so it can be compared against the reference.
"""
import asyncio
import sys
import os

# Allow running from the backend directory
sys.path.insert(0, os.path.dirname(__file__))

INPUT_DIR = "/Users/croog/Projects/Bupa/Policy Management/Build and Run/Input"
OUTPUT_PATH = "/tmp/test_output.bpmn"

PNGS = [
    "1. 6.2.3 Manage Policy maintenance.png",
    "2. 6.2.3.1 Change Policy Information.png",
    "3. 6.2.3.1.1 Process a Change of Cover.png",
    "4. 6.2.2.1 Add a person to a policy.png",
]


async def main():
    from services.claude_service import analyse_diagrams
    from services.bpmn_generator import generate_bpmn

    diagram_bytes = []
    for fname in PNGS:
        fpath = os.path.join(INPUT_DIR, fname)
        with open(fpath, "rb") as f:
            diagram_bytes.append((fname, f.read()))
        print(f"  Loaded: {fname}")

    print(f"\nAnalysing {len(diagram_bytes)} diagrams with Claude...")
    process_data, warnings = await analyse_diagrams(diagram_bytes)

    if warnings:
        print("\n⚠  Warnings:")
        for w in warnings:
            print(f"  - {w}")

    print(f"\n✓ Process name : {process_data.get('process_name')}")
    print(f"  Lanes        : {process_data.get('lanes')}")
    print(f"  Steps        : {len(process_data.get('steps', []))}")
    print(f"  Decisions    : {len(process_data.get('decisions', []))}")
    print(f"  Subprocesses : {sum(1 for s in process_data.get('steps', []) if s.get('type') == 'subprocess')}")

    print(f"\nGenerating BPMN...")
    bpmn_bytes = generate_bpmn(process_data)

    with open(OUTPUT_PATH, "wb") as f:
        f.write(bpmn_bytes)

    print(f"✓ Written to {OUTPUT_PATH}")
    print(f"  Size: {len(bpmn_bytes):,} bytes")

    # Quick structural summary
    bpmn_text = bpmn_bytes.decode("utf-8")
    print(f"\n--- Structural summary ---")
    print(f"  <collaboration>  : {'yes' if '<collaboration' in bpmn_text else 'no'}")
    print(f"  <participant>    : {bpmn_text.count('<participant ')}")
    print(f"  <process id=     : {bpmn_text.count('<process id=')}")
    print(f"  <startEvent>     : {bpmn_text.count('<startEvent ')}")
    print(f"  <endEvent>       : {bpmn_text.count('<endEvent ')}")
    print(f"  <task>           : {bpmn_text.count('<task ')}")
    print(f"  <exclusiveGateway>: {bpmn_text.count('<exclusiveGateway ')}")
    print(f"  <callActivity>   : {bpmn_text.count('<callActivity ')}")
    print(f"  <sequenceFlow>   : {bpmn_text.count('<sequenceFlow ')}")
    print(f"  <messageFlow>    : {bpmn_text.count('<messageFlow ')}")

    # Print step listing
    print(f"\n--- Steps extracted by Claude ---")
    for s in process_data.get("steps", []):
        marker = {"event": "○", "gateway": "◇", "subprocess": "▣", "task": "□"}.get(s.get("type", "task"), "?")
        print(f"  {marker} [{s['id']}] ({s.get('lane','?')}) {s.get('name','?')}")


if __name__ == "__main__":
    asyncio.run(main())
