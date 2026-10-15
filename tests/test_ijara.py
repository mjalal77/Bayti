import io
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from bayti.ijara import Actor, Asset, Customer, IjaraWorkflow, Role, Stage, Terms, WorkflowError
from bayti.ijara.cli import DEFAULT_DOC_PATH, run_demo
from bayti.ijara.definition import DOCUMENT_TYPES, STAGES
from bayti.ijara.docs import render_workflow_docs
from bayti.ijara.engine import TEMPLATE_DIR
from bayti.ijara.models import DocStatus
from bayti.ijara.schedule import add_months, build_schedule, monthly_rental

RO = Actor("Rana", Role.RELATIONSHIP_OFFICER)
COMPLIANCE = Actor("Karim", Role.COMPLIANCE_OFFICER)
COMPLIANCE_2 = Actor("Kamal", Role.COMPLIANCE_OFFICER)
CREDIT = Actor("Lina", Role.CREDIT_OFFICER)
VALUER = Actor("Omar", Role.VALUATION_OFFICER)
VALUER_2 = Actor("Osama", Role.VALUATION_OFFICER)


def make(tmp, income="30000", price="1000000", down="200000", valuation=None):
    wf = IjaraWorkflow(Path(tmp))
    app = wf.create_application(
        "A1", Customer("C1", "Test Customer", "ID-1", Decimal(income)),
        Asset("Flat 5", "Seller Co", Decimal(price)),
        Terms(Decimal(down), 120, Decimal("0.05")), RO)
    return wf, app


def finish_docs(wf, app, uploader=RO):
    """Upload and verify every required document of the current stage."""
    for code in next(s for s in STAGES if s.stage is app.stage).required_docs:
        if DOCUMENT_TYPES[code].template:
            wf.generate_document(app, code, RO)
        else:
            wf.upload_document(app, code, "f.pdf", b"x", uploader)
        v = DOCUMENT_TYPES[code].verifier
        wf.verify_document(app, code, Actor("V-" + v.value, v))


class ScheduleTests(unittest.TestCase):
    def test_schedule_fully_repays_financed_amount_and_residual(self):
        rows = build_schedule(Decimal("800000"), Decimal("0.05"), 120, Decimal("1000"), date(2026, 1, 31))
        self.assertEqual(len(rows), 120)
        self.assertEqual(sum(r.capital for r in rows), Decimal("800000") - Decimal("1000"))
        self.assertEqual(rows[-1].outstanding, Decimal("1000.00"))

    def test_zero_rate(self):
        self.assertEqual(monthly_rental(Decimal("1200"), Decimal("0"), 12, Decimal("0")), Decimal("100.00"))

    def test_month_end_dates_clamp(self):
        self.assertEqual(add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(add_months(date(2026, 11, 30), 3), date(2027, 2, 28))

    def test_bad_residual_rejected(self):
        with self.assertRaises(ValueError):
            monthly_rental(Decimal("100"), Decimal("0.05"), 12, Decimal("100"))


class DocumentRuleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.wf, self.app = make(self._tmp.name)

    def test_cannot_advance_without_verified_documents(self):
        with self.assertRaisesRegex(WorkflowError, "documents not verified"):
            self.wf.advance(self.app, RO)

    def test_uploaded_but_unverified_document_does_not_count(self):
        self.wf.upload_document(self.app, "APPLICATION_FORM", "a.pdf", b"x", RO)
        self.assertIn("APPLICATION_FORM", self.wf.missing_documents(self.app))

    def test_maker_cannot_verify_own_upload(self):
        self.wf.upload_document(self.app, "APPLICATION_FORM", "a.pdf", b"x", RO)
        with self.assertRaisesRegex(WorkflowError, "maker-checker"):
            self.wf.verify_document(self.app, "APPLICATION_FORM", RO)

    def test_wrong_role_cannot_verify(self):
        self.wf.upload_document(self.app, "NATIONAL_ID", "a.pdf", b"x", RO)
        with self.assertRaisesRegex(WorkflowError, "may not"):
            self.wf.verify_document(self.app, "NATIONAL_ID", CREDIT)

    def test_document_from_another_stage_is_refused(self):
        with self.assertRaisesRegex(WorkflowError, "not part of stage"):
            self.wf.upload_document(self.app, "KYC_FORM", "a.pdf", b"x", RO)

    def test_rejection_needs_reason_and_reupload_creates_new_version(self):
        self.wf.upload_document(self.app, "NATIONAL_ID", "a.pdf", b"v1", RO)
        with self.assertRaises(WorkflowError):
            self.wf.reject_document(self.app, "NATIONAL_ID", COMPLIANCE, " ")
        self.wf.reject_document(self.app, "NATIONAL_ID", COMPLIANCE, "blurry scan")
        self.wf.upload_document(self.app, "NATIONAL_ID", "b.pdf", b"v2", RO)
        self.assertEqual(self.app.latest("NATIONAL_ID").version, 2)
        self.assertEqual(self.app.documents["NATIONAL_ID"][0].status, DocStatus.REJECTED)
        self.wf.verify_document(self.app, "NATIONAL_ID", COMPLIANCE)

    def test_stored_file_has_hash_and_content(self):
        d = self.wf.upload_document(self.app, "NATIONAL_ID", "a.pdf", b"hello", RO)
        self.assertEqual(Path(d.path).read_bytes(), b"hello")
        self.assertEqual(len(d.sha256), 64)

    def test_upload_filename_cannot_escape_store(self):
        d = self.wf.upload_document(self.app, "NATIONAL_ID", "../../evil.pdf", b"x", RO)
        self.assertTrue(Path(d.path).resolve().is_relative_to(Path(self._tmp.name).resolve()))


class StageRuleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def to_stage(self, wf, app, target):
        while app.stage is not target:
            sd = next(s for s in STAGES if s.stage is app.stage)
            if app.stage is Stage.ASSET_VALUATION:
                wf.record_valuation(app, VALUER, app.asset.purchase_price)
            finish_docs(wf, app)
            if sd.approver:
                wf.approve_stage(app, Actor("Appr-" + sd.approver.value, sd.approver))
            wf.advance(app, Actor("Own-" + sd.owner.value, sd.owner))

    def test_approval_required_before_advancing_decision_stage(self):
        wf, app = make(self._tmp.name)
        self.to_stage(wf, app, Stage.KYC_AML)
        finish_docs(wf, app)
        with self.assertRaisesRegex(WorkflowError, "needs approval"):
            wf.advance(app, COMPLIANCE)

    def test_approver_cannot_be_preparer(self):
        wf, app = make(self._tmp.name)
        self.to_stage(wf, app, Stage.KYC_AML)
        for code in ("KYC_FORM", "SANCTIONS_SCREENING", "SOURCE_OF_FUNDS"):
            wf.upload_document(app, code, "f.pdf", b"x", COMPLIANCE)
            wf.verify_document(app, code, COMPLIANCE_2)
        with self.assertRaisesRegex(WorkflowError, "maker-checker"):
            wf.approve_stage(app, COMPLIANCE)
        wf.approve_stage(app, Actor("Other", Role.COMPLIANCE_OFFICER))

    def test_affordability_blocks_credit_approval(self):
        wf, app = make(self._tmp.name, income="3000")  # rental ~8.5k on 800k
        self.to_stage(wf, app, Stage.CREDIT_ASSESSMENT)
        finish_docs(wf, app)
        with self.assertRaisesRegex(WorkflowError, "affordability"):
            wf.approve_stage(app, Actor("Appr", Role.CREDIT_OFFICER))

    def test_valuation_required_and_caps_price(self):
        wf, app = make(self._tmp.name)
        self.to_stage(wf, app, Stage.ASSET_VALUATION)
        finish_docs(wf, app)
        with self.assertRaisesRegex(WorkflowError, "valuation"):
            wf.approve_stage(app, VALUER_2)
        wf.record_valuation(app, VALUER, Decimal("900000"))
        with self.assertRaisesRegex(WorkflowError, "exceeds the allowed maximum"):
            wf.approve_stage(app, VALUER_2)
        wf.record_valuation(app, VALUER, Decimal("1000000"))
        with self.assertRaisesRegex(WorkflowError, "recorded the valuation"):
            wf.approve_stage(app, VALUER)
        wf.approve_stage(app, VALUER_2)

    def test_lease_cannot_be_signed_before_bank_owns_asset(self):
        wf, app = make(self._tmp.name)
        self.to_stage(wf, app, Stage.ASSET_ACQUISITION)
        with self.assertRaisesRegex(WorkflowError, "not part of stage"):
            wf.generate_document(app, "IJARA_AGREEMENT", RO)
        with self.assertRaisesRegex(WorkflowError, "documents not verified"):
            wf.advance(app, Actor("Ops", Role.OPERATIONS_OFFICER))

    def test_ownership_only_after_all_rentals_paid(self):
        wf, app = make(self._tmp.name)
        self.to_stage(wf, app, Stage.LEASE_ACTIVE)
        ops = Actor("Ops", Role.OPERATIONS_OFFICER)
        with self.assertRaisesRegex(WorkflowError, "unpaid"):
            wf.advance(app, ops)
        for _ in range(app.terms.term_months):
            wf.record_rental_payment(app, ops)
        with self.assertRaisesRegex(WorkflowError, "already paid"):
            wf.record_rental_payment(app, ops)
        wf.advance(app, ops)
        self.assertIs(app.stage, Stage.OWNERSHIP_TRANSFER)

    def test_rent_not_collectable_before_delivery(self):
        wf, app = make(self._tmp.name)
        self.to_stage(wf, app, Stage.ASSET_DELIVERY)
        with self.assertRaisesRegex(WorkflowError, "only collected"):
            wf.record_rental_payment(app, Actor("Ops", Role.OPERATIONS_OFFICER))

    def test_cancel_allowed_early_blocked_after_acquisition(self):
        wf, app = make(self._tmp.name)
        self.to_stage(wf, app, Stage.OFFER)
        self.to_stage(wf, app, Stage.ASSET_ACQUISITION)
        with self.assertRaisesRegex(WorkflowError, "already owns"):
            wf.cancel(app, RO, "changed mind")

        wf2, app2 = make(self._tmp.name)
        wf2.cancel(app2, RO, "customer withdrew")
        self.assertIs(app2.stage, Stage.CANCELLED)
        with self.assertRaisesRegex(WorkflowError, "CANCELLED"):
            wf2.advance(app2, RO)

    def test_decline_by_approver_role_only(self):
        wf, app = make(self._tmp.name)
        self.to_stage(wf, app, Stage.CREDIT_ASSESSMENT)
        with self.assertRaises(WorkflowError):
            wf.decline(app, COMPLIANCE, "no")
        wf.decline(app, CREDIT, "poor history")
        self.assertIs(app.stage, Stage.REJECTED)


class GeneratedDocumentTests(unittest.TestCase):
    def test_every_template_exists_and_renders_without_placeholders(self):
        with tempfile.TemporaryDirectory() as tmp:
            wf, app = make(tmp)
            for dt in DOCUMENT_TYPES.values():
                if dt.template:
                    text = wf._render(app, dt.template)
                    self.assertNotIn("$", text, dt.code)
                    self.assertIn("DRAFT TEMPLATE", text)
        for dt in DOCUMENT_TYPES.values():
            if dt.template:
                self.assertTrue((TEMPLATE_DIR / f"{dt.template}.md.tmpl").exists())

    def test_ijara_agreement_is_separate_from_transfer_promise(self):
        with tempfile.TemporaryDirectory() as tmp:
            wf, app = make(tmp)
            self.assertNotEqual(DOCUMENT_TYPES["IJARA_AGREEMENT"].template,
                                DOCUMENT_TYPES["PROMISE_TO_TRANSFER"].template)
            text = wf._render(app, "ijara_agreement")
            self.assertIn("does not transfer ownership", text)


class DefinitionTests(unittest.TestCase):
    def test_definition_is_consistent(self):
        stages = [s.stage for s in STAGES]
        for s in STAGES:
            if s.next:
                self.assertIn(s.next, stages)
            for code in s.required_docs:
                self.assertIn(code, DOCUMENT_TYPES)
        used = {c for s in STAGES for c in s.required_docs}
        self.assertEqual(used, set(DOCUMENT_TYPES), "every document type belongs to a stage")

    def test_committed_docs_are_current(self):
        self.assertEqual(DEFAULT_DOC_PATH.read_text(), render_workflow_docs(),
                         "run: python -m bayti.ijara docs")


class EndToEndTests(unittest.TestCase):
    def test_full_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = run_demo(Path(tmp), out=io.StringIO())
            self.assertIs(app.stage, Stage.CLOSED)
            self.assertEqual(app.rentals_paid, app.terms.term_months)
            self.assertTrue(all(d.status is DocStatus.VERIFIED
                                for docs in app.documents.values() for d in docs[-1:]))
            actions = {e.action for e in app.audit}
            self.assertTrue({"CREATED", "DOC_UPLOADED", "DOC_GENERATED", "DOC_VERIFIED",
                             "STAGE_APPROVED", "STAGE_ADVANCED", "RENTAL_PAID"} <= actions)


if __name__ == "__main__":
    unittest.main()
