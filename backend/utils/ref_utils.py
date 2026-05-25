"""
Reference number utilities for Process Forge.

Handles sorting, tree-building, and gap detection for dotted process
reference numbers like 6.2.3.1.1 extracted during diagram assessment.
"""
import re

# Matches dotted numbers with at least 2 parts, e.g. 6.2 or 6.2.3.1.1
# Requires at least one dot so single integers like page numbers are ignored.
_REF_PATTERN = re.compile(r'\b(\d+(?:\.\d+){1,5})\b')

# Matches a dotted ref at the START of a filename (before any space or extension)
# e.g. "6.2.3.1 Change Policy Information.png" → "6.2.3.1"
_FILENAME_REF_PATTERN = re.compile(r'^(\d+(?:\.\d+)+)')


def identity_from_filename(filename: str) -> str | None:
    """
    Extract the process reference from the start of a filename.
    "6.2.3.1 Change Policy Information.png" → "6.2.3.1"
    Returns None if the filename doesn't start with a dotted ref.
    """
    stem = filename.rsplit('.', 1)[0].strip()
    m = _FILENAME_REF_PATTERN.match(stem)
    return m.group(1) if m else None


def ref_sort_key(ref: str) -> tuple:
    """Version-sort key: '6.2.3.1.1' → (6, 2, 3, 1, 1)"""
    try:
        return tuple(int(x) for x in ref.strip().split('.'))
    except ValueError:
        return (999,)


def extract_refs_from_text(texts: list[str]) -> list[dict]:
    """
    Fallback: scan free-text strings (notes, unclear_elements) for dotted
    reference number patterns and return them as minimal step dicts.

    These are marked type="unknown" so the UI can distinguish them from
    refs Claude explicitly extracted with full name/type context.
    Only refs with 2+ dot-separated parts are included to avoid false
    positives like version numbers or single integers.
    """
    found: dict[str, dict] = {}
    for text in texts:
        for match in _REF_PATTERN.finditer(text):
            ref = match.group(1)
            if ref not in found:
                found[ref] = {"source_ref": ref, "name": "", "type": "unknown"}
    return list(found.values())


def build_ref_nodes(steps: list[dict], fallback_texts: list[str] | None = None) -> list[dict]:
    """
    From raw step dicts returned by Claude, build a sorted, deduplicated
    list of nodes with depth info for rendering.

    Only includes steps that have a non-null source_ref.
    Deduplicates by source_ref — first occurrence wins.

    If steps is empty AND fallback_texts is provided, falls back to scanning
    those texts (notes + unclear_elements) for dotted ref patterns.

    Returns list of:
      { source_ref, name, type, depth }
    """
    seen: dict[str, dict] = {}
    for step in steps:
        ref = step.get("source_ref")
        if ref and isinstance(ref, str) and ref.strip() and ref not in seen:
            seen[ref.strip()] = step

    # If no refs were found from explicit steps, fall back to scanning free text
    if not seen and fallback_texts:
        for step in extract_refs_from_text(fallback_texts):
            ref = step.get("source_ref")
            if ref and ref not in seen:
                seen[ref] = step

    sorted_steps = sorted(seen.values(), key=lambda s: ref_sort_key(s["source_ref"]))

    return [
        {
            "source_ref": s["source_ref"].strip(),
            "name": s.get("name", "").strip(),
            "type": s.get("type", "task"),
            "depth": len(s["source_ref"].strip().split(".")) - 1,
        }
        for s in sorted_steps
    ]


def build_call_graph(
    image_refs: dict[str, list[str]],
    image_subprocess_calls: dict[str, list[str]],
) -> dict[str, list[str]]:
    """
    Build a file-level call graph from per-image subprocess reference lists.

    Each image has an IDENTITY — its minimum (shortest/topmost) ref — which
    is the process that image represents.  When image A contains a subprocess
    step pointing to ref X, and image B's identity IS X, that means A calls B.

    image_refs              — {filename: [all refs found in image]}
    image_subprocess_calls  — {filename: [source_refs of subprocess-type steps]}

    Returns an adjacency list: {filename: [called_filenames]}
    """
    # Identity of each image = ref from filename (most reliable), falling back
    # to minimum extracted ref only when the filename has no leading ref.
    # Filename is used because extracted refs include parent/caller refs that
    # appear inside child diagrams, which would poison a min-ref calculation.
    identity_to_image: dict[str, str] = {}
    for fn, refs in image_refs.items():
        primary = identity_from_filename(fn) or (min(refs, key=ref_sort_key) if refs else None)
        if primary:
            identity_to_image[primary] = fn

    call_graph: dict[str, list[str]] = {fn: [] for fn in image_refs}

    # Pass 1 — explicit subprocess-type steps from Claude's extraction
    for fn, called_refs in image_subprocess_calls.items():
        for ref in called_refs:
            target = identity_to_image.get(ref)
            if target and target != fn and target not in call_graph[fn]:
                call_graph[fn].append(target)

    # Pass 2 — structural inference fallback
    # If image A's ref list contains the identity of another uploaded image B,
    # infer A calls B. This works even when Claude doesn't label steps as
    # 'subprocess' type during assess — it just looks at which process refs
    # appear in each diagram and matches them to other uploaded images.
    if not any(v for v in call_graph.values()):
        for fn, refs in image_refs.items():
            ref_set = set(refs)
            for identity, target in identity_to_image.items():
                if target != fn and identity in ref_set and target not in call_graph[fn]:
                    call_graph[fn].append(target)

    return call_graph


def topo_sort_images(
    image_refs: dict[str, list[str]],
    call_graph: dict[str, list[str]],
) -> list[str]:
    """
    Topologically sort images so callers come before callees.

    Uses Kahn's algorithm.  Within each "layer" (same depth in the call graph),
    images are ordered by their minimum ref number for a stable, predictable
    sequence.

    If no call-graph edges exist at all, falls back to pure ref-number sort.
    Cycles (should not occur in well-formed process diagrams) are handled
    gracefully: remaining nodes after the main sort are appended in ref order.
    """
    all_files = list(image_refs.keys())

    def _ref_key(fn: str) -> tuple:
        identity = identity_from_filename(fn)
        if identity:
            return ref_sort_key(identity)
        refs = image_refs.get(fn, [])
        return min((ref_sort_key(r) for r in refs), default=(999,))

    # If there are no edges, skip the graph machinery
    if not any(v for v in call_graph.values()):
        return sorted(all_files, key=_ref_key)

    # Build in-degree counts and adjacency list (only for files we know about)
    in_degree: dict[str, int] = {fn: 0 for fn in all_files}
    adj: dict[str, list[str]] = {fn: [] for fn in all_files}

    for caller, callees in call_graph.items():
        for callee in callees:
            if callee in adj:
                adj[caller].append(callee)
                in_degree[callee] += 1

    # Seed queue with root nodes (nothing calls them), sorted by ref
    queue = sorted([fn for fn in all_files if in_degree[fn] == 0], key=_ref_key)
    result: list[str] = []

    while queue:
        node = queue.pop(0)
        result.append(node)
        new_ready = []
        for child in adj[node]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                new_ready.append(child)
        # Insert newly-ready nodes in ref order
        queue = sorted(queue + new_ready, key=_ref_key)

    # Append any remaining nodes (cycles or disconnected) in ref order
    seen = set(result)
    remaining = sorted([fn for fn in all_files if fn not in seen], key=_ref_key)
    result.extend(remaining)

    return result


def detect_gaps(nodes: list[dict]) -> list[str]:
    """
    Detect gaps within the scope of what has actually been uploaded.

    Rules:
    1. Missing parent — only flagged when the grandparent IS present, meaning
       the parent should be there but isn't. Suppressed when working with a
       subset of processes (e.g. only 6.2.3.1.x uploaded, parent 6.2.3 absent).

    2. Sibling gap — only flagged when the direct parent IS present in the
       uploaded set. If 6.2.3 is not uploaded, gaps between 6.2.3.1 and
       6.2.3.3 are not reported — those are separate process series not in scope.

    Returns a list of human-readable warning strings.
    """
    warnings: list[str] = []
    ref_set = {n["source_ref"] for n in nodes}

    # 1. Missing parents — only warn when grandparent is present
    for node in nodes:
        parts = node["source_ref"].split(".")
        if len(parts) > 2:                          # has at least a grandparent
            parent = ".".join(parts[:-1])
            grandparent = ".".join(parts[:-2])
            if parent not in ref_set and grandparent in ref_set:
                warnings.append(
                    f"Missing parent: {parent} (required by {node['source_ref']})"
                )

    # 2. Sibling gaps — only within branches whose parent IS uploaded
    by_parent: dict[str, list[int]] = {}
    for node in nodes:
        parts = node["source_ref"].split(".")
        try:
            child_num = int(parts[-1])
        except ValueError:
            continue
        parent_key = ".".join(parts[:-1]) if len(parts) > 1 else "__root__"
        # Only track siblings if their parent exists in the uploaded set
        if parent_key in ref_set or parent_key == "__root__":
            by_parent.setdefault(parent_key, []).append(child_num)

    for parent_key, children in by_parent.items():
        children_sorted = sorted(children)
        prefix = f"{parent_key}." if parent_key != "__root__" else ""
        for i in range(len(children_sorted) - 1):
            gap = children_sorted[i + 1] - children_sorted[i]
            if gap > 1:
                for missing_num in range(children_sorted[i] + 1, children_sorted[i + 1]):
                    warnings.append(
                        f"Gap: {prefix}{missing_num} not found "
                        f"(between {prefix}{children_sorted[i]} and {prefix}{children_sorted[i + 1]})"
                    )

    return warnings
