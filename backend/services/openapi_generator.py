"""
Stage 4 — OpenAPI 3.0 YAML generator.

Generates an integration connector spec: each path prefix is a named
integration system identified in the process diagrams (Apollo, Cyclops,
BizAge…). Paths are operation-specific — HTTP verbs and endpoint shapes
reflect what each system actually does in the process, NOT generic CRUD.

Process cross-references (6.x.x format) are separated from real system
integrations and listed at the bottom as downstream triggers.
"""
import re
from datetime import date


# ── String helpers ─────────────────────────────────────────────────────────────

def _to_pascal(name: str) -> str:
    return "".join(w.capitalize() for w in re.split(r"[^A-Za-z0-9]+", name) if w)


def _to_camel(name: str) -> str:
    parts = [w for w in re.split(r"[^A-Za-z0-9]+", name) if w]
    if not parts:
        return "value"
    return parts[0].lower() + "".join(p.capitalize() for p in parts[1:])


def _to_snake(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower() or "system"


def _to_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "system"


def _pluralise(word: str) -> str:
    w = word.lower()
    if w.endswith("y") and not w.endswith(("ay", "ey", "oy", "uy")):
        return w[:-1] + "ies"
    if w.endswith(("s", "x", "z", "ch", "sh")):
        return w + "es"
    return w + "s"


def _is_process_ref(name: str) -> bool:
    """True if name looks like a Bupa process cross-reference e.g. '6.2.3.1'."""
    return bool(re.match(r"^\d+\.\d+", name.strip()))


# ── Process-context inference ──────────────────────────────────────────────────

def _primary_resource(process_name: str) -> str:
    """Derive the primary business resource from the process name."""
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
    """Derive the sub-resource being acted on from the process name."""
    n = process_name.lower()
    if "cover" in n and "change" in n:
        return "cover"
    if "cover" in n:
        return "cover"
    if "person" in n or "member" in n or "add" in n:
        return "members"
    if "address" in n or "contact" in n:
        return "contact-details"
    if "payment" in n or "billing" in n:
        return "payment"
    if "cancel" in n or "terminat" in n:
        return "status"
    if "complaint" in n:
        return "complaints"
    return "details"


def _process_verb(process_name: str) -> str:
    """Derive the primary operation verb from the process name."""
    n = process_name.lower()
    if any(w in n for w in ["add", "create", "new", "register", "enrol", "open"]):
        return "create"
    if any(w in n for w in ["cancel", "terminat", "remove", "offboard", "close"]):
        return "cancel"
    return "update"   # change / modify / process / manage / update → patch


# ── Known Bupa integration system descriptions ─────────────────────────────────

_SYSTEM_META = {
    # key: lowercase system name (partial match) → (description, domain_hint)
    "apollo":               ("Core policy administration system — policy and person record management", "policy"),
    "cyclops":              ("Primary servicing system for cover changes, quotes, notes, and flags", "servicing"),
    "mybupa":               ("Customer self-service web portal and mobile app", "portal"),
    "amazon connect":       ("Telephony and IVR platform for agent-assisted interactions", "telephony"),
    "ivr":                  ("Interactive Voice Response system for self-service telephony", "telephony"),
    "product recommendation": ("Complete IT / FINFI product recommendation and eligibility engine", "recommendation"),
    "p-rex":                ("Product rules and eligibility engine", "recommendation"),
    "bizage":               ("Payment and billing system for direct debit and premium management", "billing"),
    "hugo":                 ("Internal routing platform for myBupa self-service request forwarding", "routing"),
    "sprinklr":             ("Customer communications and social engagement platform", "comms"),
    "boss":                 ("Back-office servicing system", "servicing"),
    "compass":              ("Internal knowledge and decision support tool", "knowledge"),
    "microsoft outlook":    ("Outbound partner and customer communications (M365)", "comms"),
    "microsoft forms":      ("Internal form capture and workflow initiation", "workflow"),
    "powerApps":            ("Internal low-code application platform", "workflow"),
    "vision workflow":      ("Internal workflow routing and task management system", "workflow"),
    "abda":                 ("Age-based discount assessment system", "compliance"),
    "clearance portal":     ("Portability and clearance certificate management portal", "compliance"),
    "mmcc":                 ("Membership and cover change system", "servicing"),
    "msdd":                 ("Member system data distribution", "data"),
    "msrn":                 ("Member system reference numbers", "data"),
    "mson":                 ("Member system outbound notifications", "comms"),
    "compare it":           ("Product comparison and upgrade recommendation tool", "recommendation"),
    "sitecore":             ("Digital content management and customer-facing web platform", "portal"),
    "connexions":           ("Broker and partner portal integration", "portal"),
    "stripe":               ("Card payment processing platform", "billing"),
    "paypal":               ("PayPal payment processing integration", "billing"),
    "sftp":                 ("Secure file transfer gateway for batch processing", "data"),
    "services australia":   ("Medicare and government rebate processing", "compliance"),
    "mailroom":             ("Physical and digital mail processing platform", "comms"),
}


def _system_meta(system: str) -> tuple[str, str]:
    """Return (description, domain_hint) for a system name."""
    key = system.strip().lower()
    # Exact match first
    if key in _SYSTEM_META:
        return _SYSTEM_META[key]
    # Partial match
    for k, v in _SYSTEM_META.items():
        if k in key or key in k:
            return v
    return (f"{system} integration system", "generic")


# ── Domain-specific path templates ────────────────────────────────────────────

def _policy_paths(slug, pascal, snake, res, res_l, res_pl, res_id, sub, sub_p, verb, process_name):
    """Policy administration systems (Apollo): policy + person operations."""
    write_method = {"create": "post", "cancel": "delete"}.get(verb, "patch")
    lines = [
        f"  /{slug}/{res_pl}/{{{res_id}}}:",
        f"    get:",
        f"      tags: [{pascal}]",
        f"      summary: Retrieve {res_l} record",
        f"      description: Retrieves the full {res_l} record including cover, persons, and payment details.",
        f"      operationId: {snake}Get{res}",
        f"      parameters:",
        f"        - $ref: '#/components/parameters/{res}Id'",
        f"      responses:",
        f"        '200':",
        f"          description: {res} record retrieved",
        f"          content:",
        f"            application/json:",
        f"              schema:",
        f"                $ref: '#/components/schemas/{res}Record'",
        f"        '404':",
        f"          $ref: '#/components/responses/NotFound'",
        f"",
        f"  /{slug}/{res_pl}/{{{res_id}}}/{sub}:",
        f"    {write_method}:",
        f"      tags: [{pascal}]",
        f"      summary: {'Cancel' if verb == 'cancel' else 'Update'} {sub} on {res_l}",
        f"      description: {'Cancels' if verb == 'cancel' else 'Applies a change to'} the {sub} on the {res_l} record as part of the {process_name} process.",
        f"      operationId: {snake}{_to_pascal(verb)}{res}{sub_p}",
        f"      parameters:",
        f"        - $ref: '#/components/parameters/{res}Id'",
    ]
    if verb != "cancel":
        lines += [
            f"      requestBody:",
            f"        required: true",
            f"        content:",
            f"          application/json:",
            f"            schema:",
            f"              $ref: '#/components/schemas/{res}{sub_p}Request'",
        ]
    lines += [
        f"      responses:",
        f"        '200':",
        f"          description: {sub_p} updated successfully",
        f"          content:",
        f"            application/json:",
        f"              schema:",
        f"                $ref: '#/components/schemas/{res}Record'",
        f"        '400':",
        f"          $ref: '#/components/responses/BadRequest'",
        f"        '409':",
        f"          description: Change not permitted under current {res_l} rules",
        f"",
        f"  /{slug}/{res_pl}/{{{res_id}}}/notes:",
        f"    post:",
        f"      tags: [{pascal}]",
        f"      summary: Add note or alert to {res_l}",
        f"      description: Creates an automatic or manual note on the {res_l} record. Used throughout the {process_name} process.",
        f"      operationId: {snake}AddNote",
        f"      parameters:",
        f"        - $ref: '#/components/parameters/{res}Id'",
        f"      requestBody:",
        f"        required: true",
        f"        content:",
        f"          application/json:",
        f"            schema:",
        f"              $ref: '#/components/schemas/NoteRequest'",
        f"      responses:",
        f"        '201':",
        f"          description: Note created",
        f"          content:",
        f"            application/json:",
        f"              schema:",
        f"                $ref: '#/components/schemas/NoteResponse'",
        f"        '400':",
        f"          $ref: '#/components/responses/BadRequest'",
        f"",
    ]
    return lines


def _servicing_paths(slug, pascal, snake, res, res_l, res_pl, res_id, sub, sub_p, verb, process_name):
    """Servicing systems (Cyclops): quotes, change requests, flags."""
    lines = [
        f"  /{slug}/quotes:",
        f"    post:",
        f"      tags: [{pascal}]",
        f"      summary: Generate quote for {sub} change",
        f"      description: Requests a product quote from {pascal} for the proposed {sub} change.",
        f"      operationId: {snake}CreateQuote",
        f"      requestBody:",
        f"        required: true",
        f"        content:",
        f"          application/json:",
        f"            schema:",
        f"              $ref: '#/components/schemas/{res}{sub_p}Request'",
        f"      responses:",
        f"        '201':",
        f"          description: Quote generated",
        f"          content:",
        f"            application/json:",
        f"              schema:",
        f"                $ref: '#/components/schemas/QuoteResponse'",
        f"        '400':",
        f"          $ref: '#/components/responses/BadRequest'",
        f"",
        f"  /{slug}/{res_pl}/{{{res_id}}}/changes:",
        f"    post:",
        f"      tags: [{pascal}]",
        f"      summary: Submit {sub} change request",
        f"      description: Submits the accepted {sub} change for processing in {pascal}.",
        f"      operationId: {snake}Submit{res}{sub_p}Change",
        f"      parameters:",
        f"        - $ref: '#/components/parameters/{res}Id'",
        f"      requestBody:",
        f"        required: true",
        f"        content:",
        f"          application/json:",
        f"            schema:",
        f"              $ref: '#/components/schemas/{res}{sub_p}Request'",
        f"      responses:",
        f"        '201':",
        f"          description: Change request submitted",
        f"          content:",
        f"            application/json:",
        f"              schema:",
        f"                $ref: '#/components/schemas/{res}Record'",
        f"        '400':",
        f"          $ref: '#/components/responses/BadRequest'",
        f"        '409':",
        f"          description: Change not permitted — eligibility or rule violation",
        f"",
        f"  /{slug}/{res_pl}/{{{res_id}}}/notes:",
        f"    post:",
        f"      tags: [{pascal}]",
        f"      summary: Add servicing note",
        f"      description: Records a servicing note or flag on the {res_l} in {pascal}.",
        f"      operationId: {snake}AddNote",
        f"      parameters:",
        f"        - $ref: '#/components/parameters/{res}Id'",
        f"      requestBody:",
        f"        required: true",
        f"        content:",
        f"          application/json:",
        f"            schema:",
        f"              $ref: '#/components/schemas/NoteRequest'",
        f"      responses:",
        f"        '201':",
        f"          description: Note created",
        f"          content:",
        f"            application/json:",
        f"              schema:",
        f"                $ref: '#/components/schemas/NoteResponse'",
        f"        '400':",
        f"          $ref: '#/components/responses/BadRequest'",
        f"",
    ]
    return lines


def _telephony_paths(slug, pascal, snake, res, res_l, res_pl, res_id, process_name):
    """Telephony/IVR systems (Amazon Connect, IVR): call interactions."""
    return [
        f"  /{slug}/interactions:",
        f"    post:",
        f"      tags: [{pascal}]",
        f"      summary: Initiate customer interaction",
        f"      description: Logs or initiates a customer call interaction in {pascal} for the {process_name} process.",
        f"      operationId: {snake}CreateInteraction",
        f"      requestBody:",
        f"        required: true",
        f"        content:",
        f"          application/json:",
        f"            schema:",
        f"              $ref: '#/components/schemas/InteractionRequest'",
        f"      responses:",
        f"        '201':",
        f"          description: Interaction created",
        f"          content:",
        f"            application/json:",
        f"              schema:",
        f"                $ref: '#/components/schemas/InteractionResponse'",
        f"        '400':",
        f"          $ref: '#/components/responses/BadRequest'",
        f"",
        f"  /{slug}/interactions/{{interactionId}}:",
        f"    get:",
        f"      tags: [{pascal}]",
        f"      summary: Retrieve interaction record",
        f"      description: Retrieves a call interaction record from {pascal}, including IVR path and agent routing outcome.",
        f"      operationId: {snake}GetInteraction",
        f"      parameters:",
        f"        - name: interactionId",
        f"          in: path",
        f"          required: true",
        f"          schema:",
        f"            type: string",
        f"      responses:",
        f"        '200':",
        f"          description: Interaction retrieved",
        f"          content:",
        f"            application/json:",
        f"              schema:",
        f"                $ref: '#/components/schemas/InteractionResponse'",
        f"        '404':",
        f"          $ref: '#/components/responses/NotFound'",
        f"",
    ]


def _portal_paths(slug, pascal, snake, res, res_l, res_pl, res_id, sub, sub_p, verb, process_name):
    """Customer / partner portal systems (myBupa, Hugo, Connexions): self-service requests."""
    return [
        f"  /{slug}/requests:",
        f"    post:",
        f"      tags: [{pascal}]",
        f"      summary: Submit self-service request",
        f"      description: Submits a {sub} change request through {pascal} as part of the {process_name} process.",
        f"      operationId: {snake}SubmitRequest",
        f"      requestBody:",
        f"        required: true",
        f"        content:",
        f"          application/json:",
        f"            schema:",
        f"              $ref: '#/components/schemas/{res}{sub_p}Request'",
        f"      responses:",
        f"        '201':",
        f"          description: Request submitted",
        f"          content:",
        f"            application/json:",
        f"              schema:",
        f"                $ref: '#/components/schemas/RequestResponse'",
        f"        '400':",
        f"          $ref: '#/components/responses/BadRequest'",
        f"",
        f"  /{slug}/requests/{{requestId}}:",
        f"    get:",
        f"      tags: [{pascal}]",
        f"      summary: Retrieve request status",
        f"      description: Retrieves the status of a self-service request from {pascal}.",
        f"      operationId: {snake}GetRequest",
        f"      parameters:",
        f"        - name: requestId",
        f"          in: path",
        f"          required: true",
        f"          schema:",
        f"            type: string",
        f"      responses:",
        f"        '200':",
        f"          description: Request status retrieved",
        f"          content:",
        f"            application/json:",
        f"              schema:",
        f"                $ref: '#/components/schemas/RequestResponse'",
        f"        '404':",
        f"          $ref: '#/components/responses/NotFound'",
        f"",
    ]


def _billing_paths(slug, pascal, snake, res, res_l, res_pl, res_id, process_name):
    """Billing/payment systems (BizAge, Stripe, PayPal): billing and premium operations."""
    return [
        f"  /{slug}/{res_pl}/{{{res_id}}}/billing:",
        f"    get:",
        f"      tags: [{pascal}]",
        f"      summary: Retrieve billing details",
        f"      description: Retrieves the current billing schedule and payment details from {pascal}.",
        f"      operationId: {snake}GetBilling",
        f"      parameters:",
        f"        - $ref: '#/components/parameters/{res}Id'",
        f"      responses:",
        f"        '200':",
        f"          description: Billing details retrieved",
        f"          content:",
        f"            application/json:",
        f"              schema:",
        f"                $ref: '#/components/schemas/BillingRecord'",
        f"        '404':",
        f"          $ref: '#/components/responses/NotFound'",
        f"",
        f"  /{slug}/{res_pl}/{{{res_id}}}/billing/recalculate:",
        f"    post:",
        f"      tags: [{pascal}]",
        f"      summary: Recalculate premium",
        f"      description: Triggers a premium recalculation in {pascal} following the {process_name} change.",
        f"      operationId: {snake}RecalculatePremium",
        f"      parameters:",
        f"        - $ref: '#/components/parameters/{res}Id'",
        f"      requestBody:",
        f"        required: true",
        f"        content:",
        f"          application/json:",
        f"            schema:",
        f"              $ref: '#/components/schemas/BillingRecalculateRequest'",
        f"      responses:",
        f"        '200':",
        f"          description: Premium recalculated",
        f"          content:",
        f"            application/json:",
        f"              schema:",
        f"                $ref: '#/components/schemas/BillingRecord'",
        f"        '400':",
        f"          $ref: '#/components/responses/BadRequest'",
        f"",
    ]


def _comms_paths(slug, pascal, snake, res, res_l, res_pl, res_id, process_name):
    """Communications systems (Outlook, Sprinklr, MSON): notifications and correspondence."""
    return [
        f"  /{slug}/notifications:",
        f"    post:",
        f"      tags: [{pascal}]",
        f"      summary: Send process notification",
        f"      description: Sends an outbound notification via {pascal} following the {process_name} process outcome.",
        f"      operationId: {snake}SendNotification",
        f"      requestBody:",
        f"        required: true",
        f"        content:",
        f"          application/json:",
        f"            schema:",
        f"              $ref: '#/components/schemas/NotificationRequest'",
        f"      responses:",
        f"        '201':",
        f"          description: Notification sent",
        f"          content:",
        f"            application/json:",
        f"              schema:",
        f"                $ref: '#/components/schemas/NotificationResponse'",
        f"        '400':",
        f"          $ref: '#/components/responses/BadRequest'",
        f"",
    ]


def _recommendation_paths(slug, pascal, snake, res, res_l, res_pl, res_id, sub, sub_p, process_name):
    """Product recommendation / eligibility systems (P-REX, Compare It)."""
    return [
        f"  /{slug}/eligibility:",
        f"    post:",
        f"      tags: [{pascal}]",
        f"      summary: Check {sub} eligibility",
        f"      description: Checks whether the customer is eligible for the proposed {sub} change via {pascal}.",
        f"      operationId: {snake}CheckEligibility",
        f"      requestBody:",
        f"        required: true",
        f"        content:",
        f"          application/json:",
        f"            schema:",
        f"              $ref: '#/components/schemas/{res}{sub_p}Request'",
        f"      responses:",
        f"        '200':",
        f"          description: Eligibility result",
        f"          content:",
        f"            application/json:",
        f"              schema:",
        f"                $ref: '#/components/schemas/EligibilityResponse'",
        f"        '400':",
        f"          $ref: '#/components/responses/BadRequest'",
        f"",
        f"  /{slug}/recommendations:",
        f"    post:",
        f"      tags: [{pascal}]",
        f"      summary: Get product recommendations",
        f"      description: Returns ranked product recommendations from {pascal} for the {process_name} process.",
        f"      operationId: {snake}GetRecommendations",
        f"      requestBody:",
        f"        required: true",
        f"        content:",
        f"          application/json:",
        f"            schema:",
        f"              $ref: '#/components/schemas/{res}Record'",
        f"      responses:",
        f"        '200':",
        f"          description: Recommendations returned",
        f"          content:",
        f"            application/json:",
        f"              schema:",
        f"                $ref: '#/components/schemas/RecommendationResponse'",
        f"        '400':",
        f"          $ref: '#/components/responses/BadRequest'",
        f"",
    ]


def _workflow_paths(slug, pascal, snake, process_name):
    """Workflow / routing systems (Vision Workflow, PowerApps, IWD)."""
    return [
        f"  /{slug}/tasks:",
        f"    post:",
        f"      tags: [{pascal}]",
        f"      summary: Create workflow task",
        f"      description: Creates a routing or approval task in {pascal} for the {process_name} process.",
        f"      operationId: {snake}CreateTask",
        f"      requestBody:",
        f"        required: true",
        f"        content:",
        f"          application/json:",
        f"            schema:",
        f"              $ref: '#/components/schemas/WorkflowTaskRequest'",
        f"      responses:",
        f"        '201':",
        f"          description: Task created",
        f"          content:",
        f"            application/json:",
        f"              schema:",
        f"                $ref: '#/components/schemas/WorkflowTaskResponse'",
        f"        '400':",
        f"          $ref: '#/components/responses/BadRequest'",
        f"",
        f"  /{slug}/tasks/{{taskId}}/complete:",
        f"    post:",
        f"      tags: [{pascal}]",
        f"      summary: Complete workflow task",
        f"      description: Marks a workflow task as completed in {pascal} and advances the process.",
        f"      operationId: {snake}CompleteTask",
        f"      parameters:",
        f"        - name: taskId",
        f"          in: path",
        f"          required: true",
        f"          schema:",
        f"            type: string",
        f"      requestBody:",
        f"        required: true",
        f"        content:",
        f"          application/json:",
        f"            schema:",
        f"              $ref: '#/components/schemas/WorkflowTaskRequest'",
        f"      responses:",
        f"        '200':",
        f"          description: Task completed",
        f"          content:",
        f"            application/json:",
        f"              schema:",
        f"                $ref: '#/components/schemas/WorkflowTaskResponse'",
        f"        '400':",
        f"          $ref: '#/components/responses/BadRequest'",
        f"",
    ]


def _compliance_paths(slug, pascal, snake, res, res_l, res_pl, res_id, process_name):
    """Compliance systems (ABDA, Clearance Portal, Services Australia)."""
    return [
        f"  /{slug}/checks:",
        f"    post:",
        f"      tags: [{pascal}]",
        f"      summary: Submit compliance check",
        f"      description: Submits a compliance or regulatory check request to {pascal} as part of the {process_name} process.",
        f"      operationId: {snake}SubmitCheck",
        f"      requestBody:",
        f"        required: true",
        f"        content:",
        f"          application/json:",
        f"            schema:",
        f"              $ref: '#/components/schemas/{res}Record'",
        f"      responses:",
        f"        '201':",
        f"          description: Compliance check submitted",
        f"          content:",
        f"            application/json:",
        f"              schema:",
        f"                $ref: '#/components/schemas/ComplianceCheckResponse'",
        f"        '400':",
        f"          $ref: '#/components/responses/BadRequest'",
        f"",
        f"  /{slug}/checks/{{checkId}}:",
        f"    get:",
        f"      tags: [{pascal}]",
        f"      summary: Retrieve compliance check result",
        f"      description: Retrieves the result of a compliance check from {pascal}.",
        f"      operationId: {snake}GetCheckResult",
        f"      parameters:",
        f"        - name: checkId",
        f"          in: path",
        f"          required: true",
        f"          schema:",
        f"            type: string",
        f"      responses:",
        f"        '200':",
        f"          description: Compliance check result retrieved",
        f"          content:",
        f"            application/json:",
        f"              schema:",
        f"                $ref: '#/components/schemas/ComplianceCheckResponse'",
        f"        '404':",
        f"          $ref: '#/components/responses/NotFound'",
        f"",
    ]


def _generic_paths(slug, pascal, snake, res, res_l, res_pl, res_id, process_name):
    """Fallback for unknown systems: retrieve + event/notify."""
    return [
        f"  /{slug}/{res_pl}/{{{res_id}}}:",
        f"    get:",
        f"      tags: [{pascal}]",
        f"      summary: Retrieve {res_l} from {pascal}",
        f"      description: Retrieves a {res_l} record from {pascal} during the {process_name} process.",
        f"      operationId: {snake}Get{res}",
        f"      parameters:",
        f"        - $ref: '#/components/parameters/{res}Id'",
        f"      responses:",
        f"        '200':",
        f"          description: Record retrieved",
        f"          content:",
        f"            application/json:",
        f"              schema:",
        f"                $ref: '#/components/schemas/{res}Record'",
        f"        '404':",
        f"          $ref: '#/components/responses/NotFound'",
        f"",
        f"  /{slug}/events:",
        f"    post:",
        f"      tags: [{pascal}]",
        f"      summary: Send process event to {pascal}",
        f"      description: Notifies {pascal} of a process outcome or state change during the {process_name} process.",
        f"      operationId: {snake}SendEvent",
        f"      requestBody:",
        f"        required: true",
        f"        content:",
        f"          application/json:",
        f"            schema:",
        f"              $ref: '#/components/schemas/ProcessEvent'",
        f"      responses:",
        f"        '201':",
        f"          description: Event received",
        f"        '400':",
        f"          $ref: '#/components/responses/BadRequest'",
        f"",
    ]


def _paths_for_system(
    system: str,
    process_name: str,
    primary_resource: str,
    sub_res: str,
    verb: str,
    steps: list[dict],
) -> list[str]:
    """
    Dispatch to the correct domain-specific path generator based on
    the system's known domain. Falls back to generic paths for unknowns.
    """
    slug   = _to_slug(system)
    pascal = _to_pascal(system)
    snake  = _to_snake(system)
    res    = primary_resource
    res_l  = res.lower()
    res_pl = _pluralise(res_l)
    res_id = _to_camel(res) + "Id"
    sub    = sub_res
    sub_p  = _to_pascal(sub.replace("-", " "))

    _, domain = _system_meta(system)

    if domain == "policy":
        return _policy_paths(slug, pascal, snake, res, res_l, res_pl, res_id, sub, sub_p, verb, process_name)
    if domain == "servicing":
        return _servicing_paths(slug, pascal, snake, res, res_l, res_pl, res_id, sub, sub_p, verb, process_name)
    if domain == "telephony":
        return _telephony_paths(slug, pascal, snake, res, res_l, res_pl, res_id, process_name)
    if domain in ("portal", "routing"):
        return _portal_paths(slug, pascal, snake, res, res_l, res_pl, res_id, sub, sub_p, verb, process_name)
    if domain == "billing":
        return _billing_paths(slug, pascal, snake, res, res_l, res_pl, res_id, process_name)
    if domain in ("comms", "data"):
        return _comms_paths(slug, pascal, snake, res, res_l, res_pl, res_id, process_name)
    if domain == "recommendation":
        return _recommendation_paths(slug, pascal, snake, res, res_l, res_pl, res_id, sub, sub_p, process_name)
    if domain == "workflow":
        return _workflow_paths(slug, pascal, snake, process_name)
    if domain == "compliance":
        return _compliance_paths(slug, pascal, snake, res, res_l, res_pl, res_id, process_name)
    return _generic_paths(slug, pascal, snake, res, res_l, res_pl, res_id, process_name)


# ── Components section ─────────────────────────────────────────────────────────

def _build_components(
    process_name: str,
    primary_resource: str,
    sub_res: str,
    process_refs: list[str],
) -> list[str]:
    res     = primary_resource
    res_l   = res.lower()
    res_id  = _to_camel(res) + "Id"
    sub     = sub_res
    sub_p   = _to_pascal(sub.replace("-", " "))

    lines = [
        "components:",
        "",
        "  securitySchemes:",
        "    bearerAuth:",
        "      type: http",
        "      scheme: bearer",
        "      bearerFormat: JWT",
        "",
        "  parameters:",
        f"    {res}Id:",
        f"      name: {res_id}",
        "      in: path",
        "      required: true",
        "      schema:",
        "        type: string",
        f"      description: Unique identifier for the {res_l} record",
        "",
        "  responses:",
        "    NotFound:",
        "      description: Resource not found",
        "      content:",
        "        application/json:",
        "          schema:",
        "            $ref: '#/components/schemas/Error'",
        "    BadRequest:",
        "      description: Invalid request payload",
        "      content:",
        "        application/json:",
        "          schema:",
        "            $ref: '#/components/schemas/Error'",
        "",
        "  schemas:",
        "  # ── NOTE ON SCHEMA DESIGN ──────────────────────────────────────────────────",
        "  # Schemas use additionalProperties: true and no required constraints.",
        "  # This prevents Blueprint from auto-generating data transforms that look for",
        "  # specific properties in the case class. The connector data pages are created",
        "  # as flexible structures; data transforms are wired manually in Pega Studio.",
        "  # Property names listed under 'properties' are documentation only.",
        "  # ────────────────────────────────────────────────────────────────────────────",
        "",
        "    Error:",
        "      type: object",
        "      additionalProperties: true",
        "      properties:",
        "        code:",
        "          type: string",
        "        message:",
        "          type: string",
        "",
        f"    {res}Record:",
        f"      type: object",
        f"      description: {res} record as held in the source system. Properties are indicative — wire data transforms manually.",
        "      additionalProperties: true",
        "      properties:",
        f"        {res_id}:",
        "          type: string",
        "        status:",
        "          type: string",
        f"        {_to_camel(sub)}:",
        "          type: string",
        "        effectiveDate:",
        "          type: string",
        "          format: date",
        "        updatedAt:",
        "          type: string",
        "          format: date-time",
        "",
        f"    {res}{sub_p}Request:",
        "      type: object",
        f"      description: Request payload for {process_name}. Properties are indicative — wire data transforms manually.",
        "      additionalProperties: true",
        "      properties:",
        f"        {_to_camel(sub)}:",
        "          type: string",
        "        effectiveDate:",
        "          type: string",
        "          format: date",
        "        reason:",
        "          type: string",
        "",
        f"    {res}Request:",
        "      type: object",
        f"      description: Request payload to create a new {res_l} record.",
        "      additionalProperties: true",
        "      properties:",
        "        startDate:",
        "          type: string",
        "          format: date",
        "        status:",
        "          type: string",
        "",
        "    NoteRequest:",
        "      type: object",
        "      description: Process note or audit event",
        "      additionalProperties: true",
        "      properties:",
        "        noteType:",
        "          type: string",
        "          enum: [automatic, manual, alert, flag]",
        "        text:",
        "          type: string",
        "        createdBy:",
        "          type: string",
        "",
        "    NoteResponse:",
        "      type: object",
        "      additionalProperties: true",
        "      properties:",
        "        noteId:",
        "          type: string",
        "        createdAt:",
        "          type: string",
        "          format: date-time",
        "",
    ]

    # Extra schemas referenced by domain-specific paths
    lines += [
        "    QuoteResponse:",
        "      type: object",
        "      additionalProperties: true",
        "      properties:",
        "        quoteId:",
        "          type: string",
        "        premium:",
        "          type: number",
        "          format: float",
        "        effectiveDate:",
        "          type: string",
        "          format: date",
        "        expiresAt:",
        "          type: string",
        "          format: date-time",
        "",
        "    BillingRecord:",
        "      type: object",
        "      additionalProperties: true",
        "      properties:",
        "        billingId:",
        "          type: string",
        "        frequency:",
        "          type: string",
        "        currentPremium:",
        "          type: number",
        "          format: float",
        "        nextPaymentDate:",
        "          type: string",
        "          format: date",
        "",
        "    BillingRecalculateRequest:",
        "      type: object",
        "      additionalProperties: true",
        "      properties:",
        "        effectiveDate:",
        "          type: string",
        "          format: date",
        "        reason:",
        "          type: string",
        "",
        "    InteractionRequest:",
        "      type: object",
        "      additionalProperties: true",
        "      properties:",
        "        channel:",
        "          type: string",
        "        customerId:",
        "          type: string",
        "        reason:",
        "          type: string",
        "",
        "    InteractionResponse:",
        "      type: object",
        "      additionalProperties: true",
        "      properties:",
        "        interactionId:",
        "          type: string",
        "        status:",
        "          type: string",
        "        agentId:",
        "          type: string",
        "        startedAt:",
        "          type: string",
        "          format: date-time",
        "",
        "    RequestResponse:",
        "      type: object",
        "      additionalProperties: true",
        "      properties:",
        "        requestId:",
        "          type: string",
        "        status:",
        "          type: string",
        "        submittedAt:",
        "          type: string",
        "          format: date-time",
        "",
        "    NotificationRequest:",
        "      type: object",
        "      additionalProperties: true",
        "      properties:",
        "        channel:",
        "          type: string",
        "        recipient:",
        "          type: string",
        "        templateId:",
        "          type: string",
        "",
        "    NotificationResponse:",
        "      type: object",
        "      additionalProperties: true",
        "      properties:",
        "        notificationId:",
        "          type: string",
        "        sentAt:",
        "          type: string",
        "          format: date-time",
        "",
        "    EligibilityResponse:",
        "      type: object",
        "      additionalProperties: true",
        "      properties:",
        "        eligible:",
        "          type: boolean",
        "        reasons:",
        "          type: array",
        "          items:",
        "            type: string",
        "",
        "    RecommendationResponse:",
        "      type: object",
        "      additionalProperties: true",
        "      properties:",
        "        recommendations:",
        "          type: array",
        "          items:",
        "            type: object",
        "            additionalProperties: true",
        "",
        "    WorkflowTaskRequest:",
        "      type: object",
        "      additionalProperties: true",
        "      properties:",
        "        taskType:",
        "          type: string",
        "        assignedTo:",
        "          type: string",
        "        priority:",
        "          type: string",
        "        dueDate:",
        "          type: string",
        "          format: date",
        "",
        "    WorkflowTaskResponse:",
        "      type: object",
        "      additionalProperties: true",
        "      properties:",
        "        taskId:",
        "          type: string",
        "        status:",
        "          type: string",
        "        completedAt:",
        "          type: string",
        "          format: date-time",
        "",
        "    ComplianceCheckResponse:",
        "      type: object",
        "      additionalProperties: true",
        "      properties:",
        "        checkId:",
        "          type: string",
        "        outcome:",
        "          type: string",
        "        details:",
        "          type: array",
        "          items:",
        "            type: string",
        "",
        "    ProcessEvent:",
        "      type: object",
        "      additionalProperties: true",
        "      properties:",
        "        eventType:",
        "          type: string",
        "        sourceSystem:",
        "          type: string",
        "        payload:",
        "          type: object",
        "          additionalProperties: true",
        "        occurredAt:",
        "          type: string",
        "          format: date-time",
        "      # eventType and sourceSystem should be populated — no required constraint to avoid Blueprint mapping errors",
        "",
    ]

    if process_refs:
        lines += [
            "  # ── Downstream process cross-references ────────────────────────────────────",
            "  # These are Bupa process refs called or triggered from this process.",
            "  # They are not REST integrations — they map to <callActivity> or <subProcess>",
            "  # elements in the BPMN and should be modelled as Pega case relationships.",
        ]
        for ref in sorted(process_refs):
            lines.append(f"  # - {ref}")
        lines.append("")

    return lines


# ── Main entry point ───────────────────────────────────────────────────────────

def generate_openapi(process_data: dict) -> bytes:
    process_name: str       = process_data.get("process_name", "Process")
    integrations: list[str] = process_data.get("integrations", [])
    steps: list[dict]       = process_data.get("steps", [])
    today                   = date.today().isoformat()

    # Split integrations: real systems vs Bupa process cross-references (6.x.x)
    systems      = [i for i in integrations if not _is_process_ref(i)]
    process_refs = [i for i in integrations if _is_process_ref(i)]

    primary_resource = _primary_resource(process_name)
    sub_res          = _sub_resource(process_name)
    verb             = _process_verb(process_name)

    lines: list[str] = [
        "openapi: 3.0.3",
        "info:",
        f'  title: "{process_name} — Integration Connector Spec"',
        "  description: >",
        f"    OpenAPI specification modelling the integration touchpoints for the",
        f"    {process_name} process. Each path prefix corresponds to a named",
        "    integration system identified in the process diagrams.",
        "    Intended as a Pega Connect-REST / API connector reference spec —",
        "    not a generic data API.",
        f"    Generated by Process Forge on {today}.",
        "  version: '1.0.0'",
        "  contact:",
        "    name: Bupa HI Architecture Team",
        "  license:",
        "    name: Internal Use Only",
        "",
        "servers:",
        "  - url: https://api.bupa.com.au/v1",
        "    description: Bupa Internal API Gateway (Production)",
        "  - url: https://api-uat.bupa.com.au/v1",
        "    description: Bupa Internal API Gateway (UAT)",
        "",
        "security:",
        "  - bearerAuth: []",
        "",
    ]

    # Tags — one per real integration system
    if systems:
        lines.append("tags:")
        for system in systems:
            pascal = _to_pascal(system)
            desc, _ = _system_meta(system)
            lines.append(f"  - name: {pascal}")
            lines.append(f"    description: {desc}")
        lines.append("")

    # Paths — system-prefixed, operation-specific
    lines.append("paths:")
    lines.append("")

    if systems:
        for system in systems:
            slug = _to_slug(system)
            lines.append(f"  # {'─' * 57}")
            lines.append(f"  # {system.upper()}")
            lines.append(f"  # {'─' * 57}")
            lines.append("")
            lines.extend(_paths_for_system(
                system, process_name, primary_resource, sub_res, verb, steps
            ))
    else:
        lines += [
            "  /health:",
            "    get:",
            "      summary: Health check",
            "      operationId: healthCheck",
            "      tags: [Health]",
            "      responses:",
            "        '200':",
            "          description: OK",
            "",
        ]

    # Components
    lines.extend(_build_components(process_name, primary_resource, sub_res, process_refs))

    return "\n".join(lines).encode("utf-8")
