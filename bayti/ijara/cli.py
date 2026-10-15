"""Command line entry points: `docs` writes the workflow documentation, `demo` runs a full case."""

from __future__ import annotations

import argparse
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

from .definition import DOCUMENT_TYPES, STAGE_BY_NAME
from .docs import render_workflow_docs
from .engine import IjaraWorkflow
from .models import Actor, Asset, Customer, Role, Stage, Terms

DEFAULT_DOC_PATH = Path(__file__).resolve().parents[2] / "docs" / "ijara-workflow.md"


def run_demo(store_dir: Path, out=sys.stdout):
    wf = IjaraWorkflow(store_dir)
    ro = Actor("Rana", Role.RELATIONSHIP_OFFICER)
    people = {
        Role.COMPLIANCE_OFFICER: Actor("Karim", Role.COMPLIANCE_OFFICER),
        Role.CREDIT_OFFICER: Actor("Lina", Role.CREDIT_OFFICER),
        Role.VALUATION_OFFICER: Actor("Omar", Role.VALUATION_OFFICER),
        Role.SHARIAH_OFFICER: Actor("Sara", Role.SHARIAH_OFFICER),
        Role.LEGAL_OFFICER: Actor("Layla", Role.LEGAL_OFFICER),
        Role.OPERATIONS_OFFICER: Actor("Yusuf", Role.OPERATIONS_OFFICER),
    }
    app = wf.create_application(
        "IJ-0001",
        Customer("C-100", "Demo Customer", "784-0000-0000000-0", Decimal("30000")),
        Asset("Villa 12, Demo Community", "Demo Developer LLC", Decimal("1500000")),
        Terms(down_payment=Decimal("300000"), term_months=240, profit_rate=Decimal("0.05"),
              residual_value=Decimal("1")),
        ro)

    def run_stage():
        sd = STAGE_BY_NAME[app.stage]
        if app.stage is Stage.ASSET_VALUATION:
            wf.record_valuation(app, people[Role.VALUATION_OFFICER], Decimal("1500000"))
        for code in sd.required_docs:
            if DOCUMENT_TYPES[code].template:
                wf.generate_document(app, code, ro)
            else:
                wf.upload_document(app, code, f"{code.lower()}.pdf", b"demo " + code.encode(), ro)
            verifier = Actor("Verifier-" + DOCUMENT_TYPES[code].verifier.value, DOCUMENT_TYPES[code].verifier)
            wf.verify_document(app, code, verifier)
        if sd.approver:
            wf.approve_stage(app, Actor("Approver-" + sd.approver.value, sd.approver))
        wf.advance(app, people.get(sd.owner, ro))

    while app.stage is not Stage.LEASE_ACTIVE:
        before = app.stage
        run_stage()
        print(f"{before.value:20s} -> {app.stage.value}", file=out)
    for _ in range(app.terms.term_months):
        wf.record_rental_payment(app, people[Role.OPERATIONS_OFFICER])
    print(f"{'LEASE_ACTIVE':20s} -> after {app.rentals_paid} rentals paid", file=out)
    while app.stage is not Stage.CLOSED:
        before = app.stage
        run_stage()
        print(f"{before.value:20s} -> {app.stage.value}", file=out)
    print(f"\nDocuments stored under {store_dir / app.app_id}", file=out)
    print(f"Audit events: {len(app.audit)}", file=out)
    return app


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m bayti.ijara")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("docs", help="write the workflow documentation")
    d.add_argument("--out", type=Path, default=DEFAULT_DOC_PATH)
    d.add_argument("--check", action="store_true", help="fail if the file on disk is out of date")
    m = sub.add_parser("demo", help="run an application through every stage")
    m.add_argument("--store", type=Path, default=None, help="document store directory")
    args = p.parse_args(argv)

    if args.cmd == "docs":
        text = render_workflow_docs()
        if args.check:
            if not args.out.exists() or args.out.read_text() != text:
                print(f"{args.out} is out of date; run: python -m bayti.ijara docs", file=sys.stderr)
                return 1
            return 0
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        print(f"wrote {args.out}")
        return 0
    store = args.store or Path(tempfile.mkdtemp(prefix="ijara-demo-"))
    run_demo(store)
    return 0
