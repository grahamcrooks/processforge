"""
═══════════════════════════════════════════════════════════════════════════════
PROCESS FORGE — BPMN 2.0 Generator
═══════════════════════════════════════════════════════════════════════════════

Converts the process_data JSON from Claude Vision into a BPMN 2.0 XML file
that imports directly into Pega Blueprint.

Input:  process_data dict  (lanes, steps, decisions, sequences from Claude)
Output: BPMN 2.0 XML bytes

BPMN structure produced:
  <collaboration>          — container for all participants (swimlanes)
    <participant>          — one per swimlane identified by Claude
  <process>                — one per participant, holds the steps for that lane
    <startEvent>           — steps Claude typed as "event" at the start of a lane
    <task>                 — steps Claude typed as "task"
    <exclusiveGateway>     — steps Claude typed as "gateway" (decision diamonds)
    <callActivity>         — subprocesses Claude classified as "child_case"
                             (runs as a separate independent Pega case)
    <subProcess>           — subprocesses Claude classified as "inline"
                             (runs within the same Pega case)
    <endEvent>             — steps Claude typed as "event" at the end of a lane
    <sequenceFlow>         — the arrows connecting steps, with named branches
                             on gateway outcomes
  <messageFlow>            — cross-lane connections (between participants)

No <BPMNDiagram> layout block is included — Pega Blueprint auto-layouts on import.

Fuzzy lane matching handles minor label differences between what Claude read
and what was originally in the diagram (e.g. "Agent" matches "Agent (CC)").
═══════════════════════════════════════════════════════════════════════════════
"""
import re
import uuid as _uuid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sid(raw: str) -> str:
    """Convert any string to a safe XML id (no spaces or special chars)."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", raw).strip("_") or "id_1"


def _xe(text: str) -> str:
    """XML-escape a string."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _match_lane(step_lane: str, lanes: list[str]) -> str | None:
    """
    Fuzzy-match a step's lane string to the canonical lanes list.
    Handles partial matches (e.g. 'Agent' matches 'Agent (Contact Centre)').
    """
    if step_lane in lanes:
        return step_lane
    sl = step_lane.lower()
    for lane in lanes:
        if sl in lane.lower() or lane.lower() in sl:
            return lane
    return None


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_bpmn(process_data: dict) -> bytes:
    steps: list[dict]   = process_data.get("steps", [])
    lanes: list[str]    = process_data.get("lanes", []) or ["Default"]
    process_name: str   = process_data.get("process_name", "Process")
    decisions: dict     = {d["id"]: d for d in process_data.get("decisions", [])}

    step_index = {s["id"]: s for s in steps}

    # ------------------------------------------------------------------
    # Group steps into their lane (fuzzy match + fallback to first lane)
    # ------------------------------------------------------------------
    lane_steps: dict[str, list[dict]] = {lane: [] for lane in lanes}

    for step in steps:
        raw_lane = step.get("lane", "")
        matched  = _match_lane(raw_lane, lanes)
        target   = matched if matched else lanes[0]
        lane_steps[target].append(step)

    # Set of step ids reachable within the same lane
    def intra_lane_ids(lane: str) -> set[str]:
        return {s["id"] for s in lane_steps[lane]}

    # ------------------------------------------------------------------
    # Detect starts/ends per lane
    # ------------------------------------------------------------------
    def lane_starts(lane: str) -> set[str]:
        ids = intra_lane_ids(lane)
        incoming = set()
        for s in lane_steps[lane]:
            for seq in s.get("sequence", []):
                if seq in ids:
                    incoming.add(seq)
        return ids - incoming

    def lane_ends(lane: str) -> set[str]:
        ids = intra_lane_ids(lane)
        outgoing = set()
        for s in lane_steps[lane]:
            for seq in s.get("sequence", []):
                if seq in ids:
                    outgoing.add(s["id"])
        return ids - outgoing

    # ------------------------------------------------------------------
    # Collect cross-lane message flows
    # ------------------------------------------------------------------
    message_flows: list[tuple[str, str, str]] = []   # (mf_id, src_id, tgt_id)
    mf_counter = 1
    seen_mf = set()
    for step in steps:
        src_lane = step.get("lane", "")
        for seq_target in step.get("sequence", []):
            if seq_target not in step_index:
                continue
            tgt_lane = step_index[seq_target].get("lane", "")
            sm = _match_lane(src_lane, lanes)
            tm = _match_lane(tgt_lane, lanes)
            if sm and tm and sm != tm:
                key = (step["id"], seq_target)
                if key not in seen_mf:
                    seen_mf.add(key)
                    message_flows.append((f"mf_{mf_counter}", _sid(step["id"]), _sid(seq_target)))
                    mf_counter += 1

    # ------------------------------------------------------------------
    # Collect stub sub-process ids
    # ------------------------------------------------------------------
    stub_processes: list[tuple[str, str]] = []   # (called_element_id, display_name)
    stub_seen: set[str] = set()

    for step in steps:
        if step.get("type") == "subprocess" and step.get("subtype", "inline") == "child_case":
            _sname = step.get("name", "Sub-process")
            _sref  = step.get("source_ref")
            name   = f"{_sname} ({_sref})" if _sref else _sname
            proc_id = "proc_" + _sid(_sname)[:40]   # id based on name only (stable)
            if proc_id not in stub_seen:
                stub_seen.add(proc_id)
                stub_processes.append((proc_id, name))

    # ------------------------------------------------------------------
    # Build XML lines
    # ------------------------------------------------------------------
    L: list[str] = []

    def w(line: str = "") -> None:
        L.append(line)

    w('<?xml version="1.0" encoding="UTF-8"?>')
    w('<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"')
    w('             xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"')
    w('             xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"')
    w('             xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"')
    w('             xmlns:di="http://www.omg.org/spec/DD/20100524/DI"')
    w(f'             id="definitions_1"')
    w(f'             targetNamespace="http://bupa.com.au/bpmn/1"')
    w(f'             name="{_xe(process_name)}">')
    w()

    # ------------------------------------------------------------------
    # Collaboration (only if >1 lane)
    # ------------------------------------------------------------------
    if len(lanes) > 1:
        w('  <collaboration id="collab_1">')
        for i, lane in enumerate(lanes):
            proc_ref = f"proc_{i + 1}"
            w(f'    <participant id="pool_{i + 1}" name="{_xe(lane)}" processRef="{proc_ref}"/>')
        for mf_id, src_id, tgt_id in message_flows:
            w(f'    <messageFlow id="{mf_id}" sourceRef="{src_id}" targetRef="{tgt_id}"/>')
        w('  </collaboration>')
        w()

    # ------------------------------------------------------------------
    # One <process> per lane
    # ------------------------------------------------------------------
    for i, lane in enumerate(lanes):
        proc_id    = f"proc_{i + 1}"
        executable = "true" if i == 0 else "false"
        starts     = lane_starts(lane)
        ends       = lane_ends(lane)
        intra_ids  = intra_lane_ids(lane)

        w(f'  <!-- {lane.upper()} -->')
        w(f'  <process id="{proc_id}" name="{_xe(lane)}" isExecutable="{executable}">')

        # Check whether this process will have a real startEvent from Claude's data
        has_event_start = any(
            s.get("type") == "event" and s["id"] in starts
            for s in lane_steps[lane]
        )

        # If there are steps but no event-typed start, synthesise one so Blueprint
        # always gets a valid process with a startEvent.
        if lane_steps[lane] and not has_event_start:
            syn_se_id  = f"se_syn_{i + 1}"
            first_sid  = _sid(lane_steps[lane][0]["id"])
            w(f'    <startEvent id="{syn_se_id}" name="Start"/>')
            # Wire it to the first step — add after elements via a flag
            _syn_start = (syn_se_id, first_sid, proc_id)
        else:
            _syn_start = None

        # Elements
        # Only steps Claude explicitly typed as "event" become startEvent/endEvent.
        # Tasks and gateways keep their type regardless of sequence position.
        for step in lane_steps[lane]:
            sid   = _sid(step["id"])
            stype = step.get("type", "task")
            _raw_name = step.get("name", "Step")
            _ref      = step.get("source_ref")
            name  = _xe(f"{_raw_name} ({_ref})" if _ref else _raw_name)

            if stype == "event" and step["id"] in starts:
                w(f'    <startEvent id="{sid}" name="{name}"/>')

            elif stype == "event":
                # All other "event" typed steps are end events
                w(f'    <endEvent id="{sid}" name="{name}"/>')

            elif stype == "gateway":
                w(f'    <exclusiveGateway id="{sid}" name="{name}"/>')

            elif stype == "subprocess":
                subtype = step.get("subtype", "inline")
                if subtype == "child_case":
                    called = "proc_" + _sid(step.get("name", sid))[:40]
                    w(f'    <callActivity id="{sid}" name="{name}" calledElement="{called}"/>')
                else:
                    # inline subprocess — expanded as <subProcess> within the parent process
                    s_id = f"ss_{sid}"
                    e_id = f"se_{sid}"
                    f_id = f"sf_{sid}_inner"
                    w(f'    <subProcess id="{sid}" name="{name}">')
                    w(f'      <startEvent id="{s_id}"/>')
                    w(f'      <endEvent id="{e_id}"/>')
                    w(f'      <sequenceFlow id="{f_id}" sourceRef="{s_id}" targetRef="{e_id}"/>')
                    w(f'    </subProcess>')

            else:  # task (default) — never promoted to event
                w(f'    <task id="{sid}" name="{name}"/>')

        # Sequence flows (intra-lane only)
        sf_counter = 1

        # Emit synthetic start flow if needed
        if _syn_start:
            se_id, tgt_id, pid = _syn_start
            w(f'    <sequenceFlow id="sf_{pid}_syn" sourceRef="{se_id}" targetRef="{tgt_id}"/>')

        for step in lane_steps[lane]:
            src_id   = _sid(step["id"])
            decision = decisions.get(step["id"])
            outcomes = decision.get("outcomes", []) if decision else []

            intra_targets = [t for t in step.get("sequence", []) if t in intra_ids]

            for j, target in enumerate(intra_targets):
                tgt_id  = _sid(target)
                flow_id = f"sf_{proc_id}_{sf_counter}"
                sf_counter += 1

                name_attr = ""
                if step.get("type") == "gateway" and j < len(outcomes):
                    name_attr = f' name="{_xe(outcomes[j])}"'

                w(f'    <sequenceFlow id="{flow_id}" sourceRef="{src_id}" targetRef="{tgt_id}"{name_attr}/>')

        w('  </process>')
        w()

    # ------------------------------------------------------------------
    # Stub sub-processes referenced by callActivity elements
    # ------------------------------------------------------------------
    if stub_processes:
        w('  <!-- STUB SUB-PROCESSES -->')
        for proc_id, display_name in stub_processes:
            s_id = f"s_{proc_id}"
            e_id = f"e_{proc_id}"
            f_id = f"f_{proc_id}"
            w(f'  <process id="{proc_id}" name="{_xe(display_name)}" isExecutable="false">'
              f'<startEvent id="{s_id}"/><endEvent id="{e_id}"/>'
              f'<sequenceFlow id="{f_id}" sourceRef="{s_id}" targetRef="{e_id}"/></process>')
        w()

    w('</definitions>')

    return "\n".join(L).encode("utf-8")
