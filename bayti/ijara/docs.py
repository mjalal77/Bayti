"""Generates the workflow documentation from the workflow definition."""

from __future__ import annotations

from .definition import CANCELLABLE, DOCUMENT_TYPES, STAGES
from .models import Stage


def _role(r) -> str:
    return r.value.replace("_", " ")


def mermaid() -> str:
    lines = ["stateDiagram-v2", "    [*] --> DRAFT"]
    for s in STAGES:
        if s.next:
            lines.append(f"    {s.stage.value} --> {s.next.value}")
    lines.append("    CLOSED --> [*]")
    for st in sorted(CANCELLABLE, key=lambda x: x.value):
        lines.append(f"    {st.value} --> CANCELLED")
    for s in STAGES:
        if s.approver and s.stage in CANCELLABLE:
            lines.append(f"    {s.stage.value} --> REJECTED")
    return "\n".join(lines)


def render_workflow_docs() -> str:
    out = [
        "# Ijara Financing Workflow",
        "",
        "> Generated from `bayti/ijara/definition.py` by `python -m bayti.ijara docs`. "
        "Do not edit by hand; change the definition and regenerate.",
        "",
        "Ijara Muntahia Bittamleek is a lease that ends with the customer owning the asset. "
        "This workflow moves an application from request to title transfer and "
        "blocks every step that lacks its verified documents or approvals.",
        "",
        "## Flow",
        "",
        "```mermaid",
        mermaid(),
        "```",
        "",
        "## Rules enforced by the system",
        "",
        "- **Documents gate stages.** A stage cannot be left until each of its required documents "
        "has been uploaded (or generated) and verified. Re-uploads create a new version; only the latest counts.",
        "- **Maker-checker.** Nobody can verify a document they uploaded, and the stage approver cannot be "
        "the person who prepared that stage's documents.",
        "- **Role authority.** Each document type names the role allowed to verify it; each decision stage "
        "names its approver role.",
        "- **Ownership before lease.** The ASSET_ACQUISITION stage needs title in the bank's name and a takaful "
        "policy before the Ijara agreement can be prepared.",
        "- **Separate promise to transfer.** The promise to transfer ownership is its own document, not a clause "
        "of the lease.",
        "- **Rent starts on delivery.** Rent is collected only after the delivery certificate is verified.",
        "- **Ownership transfers after full payment.** LEASE_ACTIVE cannot advance until every rental is paid.",
        "- **Exit.** Applications can be cancelled until the bank buys the asset. After that, an unwind is manual.",
        "- **Audit trail.** Every upload, verification, rejection, approval and stage change is logged with actor "
        "and time. Stored files carry a SHA-256 hash.",
        "",
        "## Stages",
        "",
    ]
    for i, s in enumerate(STAGES, 1):
        out += [f"### {i}. {s.stage.value}", "", s.purpose, ""]
        out.append(f"- **Owner:** {_role(s.owner)}")
        if s.approver:
            out.append(f"- **Approval by:** {_role(s.approver)}")
        out.append(f"- **Next stage:** {s.next.value if s.next else 'none (end of workflow)'}")
        if s.notes:
            out.append(f"- **Note:** {s.notes}")
        if s.required_docs:
            out += ["", "| Required document | Verified by | Source |", "|---|---|---|"]
            for code in s.required_docs:
                d = DOCUMENT_TYPES[code]
                src = "Generated from template, then signed" if d.template else "Uploaded"
                out.append(f"| {d.title} (`{code}`) | {_role(d.verifier)} | {src} |")
        out.append("")
    out += ["## Stage-specific checks", "",
            "| Stage | Check |", "|---|---|",
            "| CREDIT_ASSESSMENT | Monthly rental must not exceed the policy share of monthly income (default 50%). |",
            "| ASSET_VALUATION | An independent valuation must be recorded by someone other than the approver, and the purchase "
            "price must not exceed the policy share of that valuation (default 100%). |",
            "| LEASE_ACTIVE | All rentals paid before ownership transfer. |",
            "",
            "Policy defaults live in `Policy` in `bayti/ijara/engine.py` and are placeholders until set from the "
            "bank's approved credit policy.",
            "",
            "## Generated documents", "",
            "Templates are in `bayti/ijara/templates/`. They are **drafts**: Legal and the Shariah Supervisory Board "
            "must approve the final wording before customer use.",
            ""]
    for d in DOCUMENT_TYPES.values():
        if d.template:
            out.append(f"- {d.title}: `{d.template}.md.tmpl`")
    out.append("")
    return "\n".join(out)
