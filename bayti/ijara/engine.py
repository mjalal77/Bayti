"""Workflow engine: enforces stage gates, role authority, maker-checker and audit."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from string import Template
from typing import Dict, Optional

from .definition import CANCELLABLE, DOCUMENT_TYPES, STAGE_BY_NAME
from .models import (Actor, Application, Asset, Customer, Document, DocStatus, Role, Stage, Terms)
from .schedule import build_schedule, monthly_rental

TEMPLATE_DIR = Path(__file__).parent / "templates"


class WorkflowError(Exception):
    """Raised when an action is not allowed in the current state."""


@dataclass(frozen=True)
class Policy:
    """Bank policy knobs. The defaults are placeholders: set them from approved credit policy."""

    bank_name: str = "Al Salam Bank"
    # Maximum monthly rental as a share of monthly income.
    max_rental_to_income: Decimal = Decimal("0.50")
    # Maximum purchase price as a share of the independent valuation.
    max_price_to_valuation: Decimal = Decimal("1.00")


class IjaraWorkflow:
    def __init__(self, store_dir: Path, policy: Optional[Policy] = None):
        self.store_dir = Path(store_dir)
        self.policy = policy or Policy()

    # ---- application lifecycle -------------------------------------------------

    def create_application(self, app_id: str, customer: Customer, asset: Asset, terms: Terms,
                           actor: Actor) -> Application:
        self._require_role(actor, Role.RELATIONSHIP_OFFICER, "create applications")
        app = Application(app_id, customer, asset, terms, created_by=actor.name)
        # Validates the commercial terms up front (raises ValueError if unworkable).
        monthly_rental(app.financed_amount, terms.profit_rate, terms.term_months, terms.residual_value)
        app.log(actor.name, "CREATED", f"financed {app.financed_amount}")
        return app

    def rental(self, app: Application) -> Decimal:
        t = app.terms
        return monthly_rental(app.financed_amount, t.profit_rate, t.term_months, t.residual_value)

    def cancel(self, app: Application, actor: Actor, reason: str) -> None:
        self._require_open(app)
        self._require_role(actor, Role.RELATIONSHIP_OFFICER, "cancel an application")
        if app.stage not in CANCELLABLE:
            raise WorkflowError(
                f"cannot cancel in {app.stage.value}: the bank already owns the asset; "
                "an unwind must be handled manually by Legal and Operations")
        self._close(app, actor, Stage.CANCELLED, reason, "CANCELLED")

    def decline(self, app: Application, actor: Actor, reason: str) -> None:
        sd = STAGE_BY_NAME[app.stage]
        self._require_open(app)
        if sd.approver is None or app.stage not in CANCELLABLE:
            raise WorkflowError(f"{app.stage.value} has no decision point to decline at")
        self._require_role(actor, sd.approver, "decline at this stage")
        self._close(app, actor, Stage.REJECTED, reason, "DECLINED")

    # ---- documents -------------------------------------------------------------

    def upload_document(self, app: Application, doc_type: str, filename: str, content: bytes,
                        actor: Actor) -> Document:
        self._require_open(app)
        self._check_doc_type(app, doc_type)
        versions = app.documents.setdefault(doc_type, [])
        version = len(versions) + 1
        doc = self._store(app, doc_type, filename, content, actor.name, version, generated=False)
        versions.append(doc)
        app.log(actor.name, "DOC_UPLOADED", f"{doc_type} v{version} ({filename})")
        return doc

    def generate_document(self, app: Application, doc_type: str, actor: Actor) -> Document:
        """Render a bank-issued document from its template into the document store."""
        self._require_open(app)
        self._check_doc_type(app, doc_type)
        dt = DOCUMENT_TYPES[doc_type]
        if not dt.template:
            raise WorkflowError(f"{doc_type} is not a bank-generated document; upload it instead")
        self._require_role(actor, Role.RELATIONSHIP_OFFICER, "generate documents", also=(dt.verifier, Role.SYSTEM))
        text = self._render(app, dt.template)
        versions = app.documents.setdefault(doc_type, [])
        version = len(versions) + 1
        doc = self._store(app, doc_type, f"{doc_type.lower()}.md", text.encode(), "system", version, generated=True)
        versions.append(doc)
        app.log(actor.name, "DOC_GENERATED", f"{doc_type} v{version}")
        return doc

    def verify_document(self, app: Application, doc_type: str, actor: Actor) -> None:
        doc = self._reviewable(app, doc_type, actor)
        doc.status, doc.verified_by, doc.verified_at = DocStatus.VERIFIED, actor.name, _now()
        app.log(actor.name, "DOC_VERIFIED", f"{doc_type} v{doc.version}")

    def reject_document(self, app: Application, doc_type: str, actor: Actor, reason: str) -> None:
        if not reason.strip():
            raise WorkflowError("a rejection reason is required")
        doc = self._reviewable(app, doc_type, actor)
        doc.status, doc.rejection_reason = DocStatus.REJECTED, reason
        app.log(actor.name, "DOC_REJECTED", f"{doc_type} v{doc.version}: {reason}")

    def missing_documents(self, app: Application) -> list:
        """Required documents for the current stage that are not yet VERIFIED."""
        sd = STAGE_BY_NAME[app.stage]
        return [c for c in sd.required_docs
                if not (app.latest(c) and app.latest(c).status is DocStatus.VERIFIED)]

    # ---- decisions and stage movement -----------------------------------------

    def record_valuation(self, app: Application, actor: Actor, amount: Decimal) -> None:
        self._require_open(app)
        if app.stage is not Stage.ASSET_VALUATION:
            raise WorkflowError("valuation can only be recorded in ASSET_VALUATION")
        self._require_role(actor, Role.VALUATION_OFFICER, "record a valuation")
        if amount <= 0:
            raise WorkflowError("valuation must be positive")
        app.asset.valuation, app.valuation_recorded_by = amount, actor.name
        app.log(actor.name, "VALUATION_RECORDED", str(amount))

    def approve_stage(self, app: Application, actor: Actor) -> None:
        self._require_open(app)
        sd = STAGE_BY_NAME[app.stage]
        if sd.approver is None:
            raise WorkflowError(f"{app.stage.value} does not need an approval")
        self._require_role(actor, sd.approver, "approve this stage")
        self._require_docs(app)
        preparers = {d.uploaded_by for c in sd.required_docs for d in [app.latest(c)] if d}
        if actor.name in preparers:
            raise WorkflowError("maker-checker: the approver cannot be the person who prepared the documents")
        if app.stage is Stage.ASSET_VALUATION and actor.name == app.valuation_recorded_by:
            raise WorkflowError("maker-checker: the approver cannot be the person who recorded the valuation")
        self._stage_guards(app)
        app.approvals[app.stage] = actor.name
        app.log(actor.name, "STAGE_APPROVED", app.stage.value)

    def advance(self, app: Application, actor: Actor) -> Stage:
        self._require_open(app)
        sd = STAGE_BY_NAME[app.stage]
        if sd.next is None:
            raise WorkflowError(f"{app.stage.value} is the last stage")
        self._require_role(actor, sd.owner, "advance this stage", also=(sd.approver,) if sd.approver else ())
        self._require_docs(app)
        if sd.approver and app.stage not in app.approvals:
            raise WorkflowError(f"{app.stage.value} needs approval by {sd.approver.value} before advancing")
        self._stage_guards(app)
        old, app.stage = app.stage, sd.next
        if old is Stage.ASSET_DELIVERY:
            app.lease_start = date.today()
        app.log(actor.name, "STAGE_ADVANCED", f"{old.value} -> {app.stage.value}")
        return app.stage

    def record_rental_payment(self, app: Application, actor: Actor) -> None:
        self._require_open(app)
        if app.stage is not Stage.LEASE_ACTIVE:
            raise WorkflowError("rent is only collected in LEASE_ACTIVE")
        self._require_role(actor, Role.OPERATIONS_OFFICER, "record rental payments")
        if app.rentals_paid >= app.terms.term_months:
            raise WorkflowError("all rentals are already paid")
        app.rentals_paid += 1
        app.log(actor.name, "RENTAL_PAID", f"{app.rentals_paid}/{app.terms.term_months}")

    def rental_schedule(self, app: Application, start: Optional[date] = None):
        t = app.terms
        return build_schedule(app.financed_amount, t.profit_rate, t.term_months, t.residual_value,
                              start or app.lease_start or date.today())

    # ---- internals -------------------------------------------------------------

    def _stage_guards(self, app: Application) -> None:
        if app.stage is Stage.CREDIT_ASSESSMENT:
            cap = app.customer.monthly_income * self.policy.max_rental_to_income
            if self.rental(app) > cap:
                raise WorkflowError(
                    f"affordability: monthly rental {self.rental(app)} exceeds {cap} "
                    f"({self.policy.max_rental_to_income:.0%} of income)")
        elif app.stage is Stage.ASSET_VALUATION:
            if app.asset.valuation is None:
                raise WorkflowError("record the independent valuation before approving")
            limit = app.asset.valuation * self.policy.max_price_to_valuation
            if app.asset.purchase_price > limit:
                raise WorkflowError(
                    f"purchase price {app.asset.purchase_price} exceeds the allowed maximum {limit} "
                    "against the valuation")
        elif app.stage is Stage.LEASE_ACTIVE:
            if app.rentals_paid < app.terms.term_months:
                raise WorkflowError(
                    f"{app.terms.term_months - app.rentals_paid} rental(s) still unpaid; "
                    "ownership transfers only after the lease term is fulfilled")

    def _require_docs(self, app: Application) -> None:
        missing = self.missing_documents(app)
        if missing:
            raise WorkflowError("documents not verified: " + ", ".join(missing))

    def _require_open(self, app: Application) -> None:
        if app.stage in (Stage.CLOSED, Stage.REJECTED, Stage.CANCELLED):
            raise WorkflowError(f"application is {app.stage.value}")

    def _require_role(self, actor: Actor, role: Role, what: str, also: tuple = ()) -> None:
        if actor.role is not role and actor.role not in also:
            raise WorkflowError(f"role {actor.role.value} may not {what} (needs {role.value})")

    def _check_doc_type(self, app: Application, doc_type: str) -> None:
        if doc_type not in DOCUMENT_TYPES:
            raise WorkflowError(f"unknown document type {doc_type}")
        if doc_type not in STAGE_BY_NAME[app.stage].required_docs:
            raise WorkflowError(f"{doc_type} is not part of stage {app.stage.value}")

    def _reviewable(self, app: Application, doc_type: str, actor: Actor) -> Document:
        self._require_open(app)
        doc = app.latest(doc_type)
        if doc is None:
            raise WorkflowError(f"no {doc_type} has been uploaded")
        if doc.status is not DocStatus.UPLOADED:
            raise WorkflowError(f"{doc_type} v{doc.version} is already {doc.status.value}")
        self._require_role(actor, DOCUMENT_TYPES[doc_type].verifier, f"review {doc_type}")
        if actor.name == doc.uploaded_by:
            raise WorkflowError("maker-checker: you cannot review a document you uploaded")
        return doc

    def _store(self, app: Application, doc_type: str, filename: str, content: bytes, by: str,
               version: int, generated: bool) -> Document:
        safe = Path(filename).name
        folder = self.store_dir / app.app_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{doc_type}_v{version}_{safe}"
        path.write_bytes(content)
        return Document(doc_type, safe, by, _now(), version, generated=generated,
                        sha256=hashlib.sha256(content).hexdigest(), path=str(path))

    def _close(self, app: Application, actor: Actor, stage: Stage, reason: str, action: str) -> None:
        if not reason.strip():
            raise WorkflowError("a reason is required")
        app.stage, app.closing_reason = stage, reason
        app.log(actor.name, action, reason)

    def _render(self, app: Application, template: str) -> str:
        t, c, a = app.terms, app.customer, app.asset
        rows = self.rental_schedule(app)
        table = "\n".join(
            f"| {r.period} | {r.due.isoformat()} | {r.rental:,.2f} | {r.profit:,.2f} | "
            f"{r.capital:,.2f} | {r.outstanding:,.2f} |" for r in rows)
        ctx: Dict[str, str] = dict(
            bank=self.policy.bank_name, app_id=app.app_id, customer=c.full_name,
            national_id=c.national_id, asset=a.description, seller=a.seller,
            price=f"{a.purchase_price:,.2f}", down_payment=f"{t.down_payment:,.2f}",
            financed=f"{app.financed_amount:,.2f}", term=str(t.term_months),
            rate=f"{t.profit_rate * 100:.2f}%", rental=f"{self.rental(app):,.2f}",
            residual=f"{t.residual_value:,.2f}", date=date.today().isoformat(),
            lease_start=(app.lease_start or date.today()).isoformat(), schedule_table=table,
        )
        raw = (TEMPLATE_DIR / f"{template}.md.tmpl").read_text()
        return Template(raw).substitute(ctx)


def _now() -> datetime:
    return datetime.now(timezone.utc)
