"""Declarative definition of the Ijara workflow.

Everything the engine enforces and everything the generated documentation
describes is read from this module, so the two cannot drift apart.

Structure follows Ijara Muntahia Bittamleek (lease ending with ownership):
the bank must own the asset before leasing it, rent starts only on delivery,
and the promise to transfer ownership is a separate undertaking from the
lease itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .models import DocumentType, Role, Stage

DOCUMENT_TYPES: Dict[str, DocumentType] = {
    d.code: d
    for d in [
        # Application and identity
        DocumentType("APPLICATION_FORM", "Financing application form", Role.RELATIONSHIP_OFFICER),
        DocumentType("NATIONAL_ID", "National ID / passport copy", Role.COMPLIANCE_OFFICER),
        DocumentType("INCOME_PROOF", "Salary certificate or income proof", Role.CREDIT_OFFICER),
        DocumentType("BANK_STATEMENTS", "Bank statements (last 6 months)", Role.CREDIT_OFFICER),
        # KYC / AML
        DocumentType("KYC_FORM", "KYC form", Role.COMPLIANCE_OFFICER),
        DocumentType("SANCTIONS_SCREENING", "Sanctions / AML screening report", Role.COMPLIANCE_OFFICER),
        DocumentType("SOURCE_OF_FUNDS", "Source of funds declaration (down payment)", Role.COMPLIANCE_OFFICER),
        # Credit
        DocumentType("CREDIT_BUREAU_REPORT", "Credit bureau report", Role.CREDIT_OFFICER),
        DocumentType("AFFORDABILITY_ASSESSMENT", "Affordability assessment", Role.CREDIT_OFFICER),
        DocumentType("CREDIT_APPROVAL_MEMO", "Credit approval memo", Role.CREDIT_OFFICER),
        # Asset
        DocumentType("TITLE_DEED", "Title deed / proof of seller ownership", Role.LEGAL_OFFICER),
        DocumentType("VALUATION_REPORT", "Independent valuation report", Role.VALUATION_OFFICER),
        DocumentType("SELLER_NOC", "Seller no-objection / encumbrance clearance", Role.LEGAL_OFFICER),
        # Shariah
        DocumentType("SHARIAH_CHECKLIST", "Shariah compliance checklist", Role.SHARIAH_OFFICER,
                     "Asset permissibility, structure conformity, no prohibited elements."),
        # Offer (generated)
        DocumentType("OFFER_LETTER", "Financing offer letter", Role.LEGAL_OFFICER, template="offer_letter"),
        DocumentType("PROMISE_TO_LEASE", "Promise to lease (Wa'd)", Role.LEGAL_OFFICER,
                     "Customer's unilateral undertaking to lease the asset once the bank owns it.",
                     template="promise_to_lease"),
        # Acquisition
        DocumentType("SALE_PURCHASE_AGREEMENT", "Sale and purchase agreement (bank buys from seller)",
                     Role.LEGAL_OFFICER),
        DocumentType("SELLER_PAYMENT_PROOF", "Proof of payment to seller", Role.OPERATIONS_OFFICER),
        DocumentType("TITLE_IN_BANK_NAME", "Title registered in the bank's name", Role.LEGAL_OFFICER,
                     "The bank must hold ownership before it can lease the asset."),
        DocumentType("TAKAFUL_POLICY", "Takaful policy (bank as owner/beneficiary)", Role.OPERATIONS_OFFICER),
        # Execution (generated)
        DocumentType("IJARA_AGREEMENT", "Ijara (lease) agreement", Role.LEGAL_OFFICER, template="ijara_agreement"),
        DocumentType("PROMISE_TO_TRANSFER", "Promise to transfer ownership (separate undertaking)", Role.LEGAL_OFFICER,
                     "Must be a separate document from the Ijara agreement.", template="promise_to_transfer"),
        DocumentType("RENTAL_SCHEDULE", "Rental schedule", Role.OPERATIONS_OFFICER, template="rental_schedule"),
        # Delivery (generated)
        DocumentType("DELIVERY_CERTIFICATE", "Delivery and acceptance certificate", Role.OPERATIONS_OFFICER,
                     "Signed delivery is the trigger for rent to start.", template="delivery_certificate"),
        # Ownership transfer (generated)
        DocumentType("FINAL_SETTLEMENT_STATEMENT", "Final settlement statement", Role.OPERATIONS_OFFICER),
        DocumentType("TRANSFER_DEED", "Ownership transfer deed (gift or sale)", Role.LEGAL_OFFICER,
                     template="transfer_deed"),
        DocumentType("TITLE_IN_CUSTOMER_NAME", "Title registered in the customer's name", Role.LEGAL_OFFICER),
    ]
}


@dataclass(frozen=True)
class StageDef:
    stage: Stage
    purpose: str
    owner: Role
    # Documents that must be VERIFIED before leaving this stage.
    required_docs: Tuple[str, ...] = ()
    # Role whose explicit approval is needed to leave this stage (maker-checker).
    approver: Optional[Role] = None
    next: Optional[Stage] = None
    notes: str = ""


STAGES: List[StageDef] = [
    StageDef(Stage.DRAFT, "Capture the request and collect customer documents.", Role.RELATIONSHIP_OFFICER,
             ("APPLICATION_FORM", "NATIONAL_ID", "INCOME_PROOF", "BANK_STATEMENTS"),
             next=Stage.KYC_AML),
    StageDef(Stage.KYC_AML, "Identify the customer and screen for sanctions and AML risk.", Role.COMPLIANCE_OFFICER,
             ("KYC_FORM", "SANCTIONS_SCREENING", "SOURCE_OF_FUNDS"),
             approver=Role.COMPLIANCE_OFFICER, next=Stage.CREDIT_ASSESSMENT),
    StageDef(Stage.CREDIT_ASSESSMENT, "Assess creditworthiness and affordability.", Role.CREDIT_OFFICER,
             ("CREDIT_BUREAU_REPORT", "AFFORDABILITY_ASSESSMENT", "CREDIT_APPROVAL_MEMO"),
             approver=Role.CREDIT_OFFICER, next=Stage.ASSET_VALUATION),
    StageDef(Stage.ASSET_VALUATION, "Confirm the seller owns the asset and its value supports the price.",
             Role.VALUATION_OFFICER, ("TITLE_DEED", "VALUATION_REPORT", "SELLER_NOC"),
             approver=Role.VALUATION_OFFICER, next=Stage.SHARIAH_REVIEW),
    StageDef(Stage.SHARIAH_REVIEW, "Confirm the asset and the deal structure are Shariah compliant.",
             Role.SHARIAH_OFFICER, ("SHARIAH_CHECKLIST",), approver=Role.SHARIAH_OFFICER, next=Stage.OFFER),
    StageDef(Stage.OFFER, "Issue the offer and obtain the customer's promise to lease.", Role.LEGAL_OFFICER,
             ("OFFER_LETTER", "PROMISE_TO_LEASE"), next=Stage.ASSET_ACQUISITION,
             notes="The promise is a unilateral undertaking; it is not the lease itself."),
    StageDef(Stage.ASSET_ACQUISITION, "The bank buys the asset and takes ownership and ownership risk.",
             Role.OPERATIONS_OFFICER,
             ("SALE_PURCHASE_AGREEMENT", "SELLER_PAYMENT_PROOF", "TITLE_IN_BANK_NAME", "TAKAFUL_POLICY"),
             next=Stage.IJARA_EXECUTION,
             notes="No lease can be signed until the bank owns the asset."),
    StageDef(Stage.IJARA_EXECUTION, "Sign the lease and the separate promise to transfer ownership.",
             Role.LEGAL_OFFICER, ("IJARA_AGREEMENT", "PROMISE_TO_TRANSFER", "RENTAL_SCHEDULE"),
             next=Stage.ASSET_DELIVERY),
    StageDef(Stage.ASSET_DELIVERY, "Hand the asset to the customer; rent starts on delivery.",
             Role.OPERATIONS_OFFICER, ("DELIVERY_CERTIFICATE",), next=Stage.LEASE_ACTIVE),
    StageDef(Stage.LEASE_ACTIVE, "Lease term: collect rent and service the asset.", Role.OPERATIONS_OFFICER,
             next=Stage.OWNERSHIP_TRANSFER,
             notes="Late-payment amounts, if any, go to charity, not to bank income."),
    StageDef(Stage.OWNERSHIP_TRANSFER, "Transfer title to the customer at the end of the lease.",
             Role.LEGAL_OFFICER, ("FINAL_SETTLEMENT_STATEMENT", "TRANSFER_DEED", "TITLE_IN_CUSTOMER_NAME"),
             next=Stage.CLOSED),
    StageDef(Stage.CLOSED, "Financing completed.", Role.OPERATIONS_OFFICER),
]

STAGE_BY_NAME: Dict[Stage, StageDef] = {s.stage: s for s in STAGES}

# Stages in which an application can still be declined or withdrawn. Once the bank has
# bought the asset (ASSET_ACQUISITION onward) it carries ownership risk, so exit is no
# longer a simple cancel and needs a separate, manual unwind.
CANCELLABLE = {
    Stage.DRAFT, Stage.KYC_AML, Stage.CREDIT_ASSESSMENT, Stage.ASSET_VALUATION,
    Stage.SHARIAH_REVIEW, Stage.OFFER,
}
