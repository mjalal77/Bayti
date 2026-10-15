"""Core data model for an Ijara (lease-to-own) financing application."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional


class Stage(str, Enum):
    DRAFT = "DRAFT"
    KYC_AML = "KYC_AML"
    CREDIT_ASSESSMENT = "CREDIT_ASSESSMENT"
    ASSET_VALUATION = "ASSET_VALUATION"
    SHARIAH_REVIEW = "SHARIAH_REVIEW"
    OFFER = "OFFER"
    ASSET_ACQUISITION = "ASSET_ACQUISITION"
    IJARA_EXECUTION = "IJARA_EXECUTION"
    ASSET_DELIVERY = "ASSET_DELIVERY"
    LEASE_ACTIVE = "LEASE_ACTIVE"
    OWNERSHIP_TRANSFER = "OWNERSHIP_TRANSFER"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class Role(str, Enum):
    RELATIONSHIP_OFFICER = "relationship_officer"
    COMPLIANCE_OFFICER = "compliance_officer"
    CREDIT_OFFICER = "credit_officer"
    VALUATION_OFFICER = "valuation_officer"
    SHARIAH_OFFICER = "shariah_officer"
    LEGAL_OFFICER = "legal_officer"
    OPERATIONS_OFFICER = "operations_officer"
    SYSTEM = "system"


class DocStatus(str, Enum):
    UPLOADED = "UPLOADED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class Actor:
    name: str
    role: Role


@dataclass(frozen=True)
class DocumentType:
    """A kind of document the workflow can require or generate."""

    code: str
    title: str
    verifier: Role
    description: str = ""
    # Name of a template in templates/ if the bank generates this document.
    template: Optional[str] = None


@dataclass
class Document:
    doc_type: str
    filename: str
    uploaded_by: str
    uploaded_at: datetime
    version: int = 1
    status: DocStatus = DocStatus.UPLOADED
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    generated: bool = False
    sha256: str = ""
    path: str = ""


@dataclass
class AuditEvent:
    at: datetime
    actor: str
    action: str
    detail: str


@dataclass
class Customer:
    customer_id: str
    full_name: str
    national_id: str
    monthly_income: Decimal


@dataclass
class Asset:
    description: str
    seller: str
    purchase_price: Decimal
    valuation: Optional[Decimal] = None


@dataclass
class Terms:
    """Commercial terms of the lease. Rates are annual, as fractions (0.05 = 5%)."""

    down_payment: Decimal
    term_months: int
    profit_rate: Decimal
    residual_value: Decimal = Decimal("0")


@dataclass
class Application:
    app_id: str
    customer: Customer
    asset: Asset
    terms: Terms
    created_by: str
    stage: Stage = Stage.DRAFT
    # All versions are kept; the latest version of each type is the effective one.
    documents: Dict[str, List[Document]] = field(default_factory=dict)
    audit: List[AuditEvent] = field(default_factory=list)
    # Stage -> approver name for stages that need an explicit decision.
    approvals: Dict[Stage, str] = field(default_factory=dict)
    valuation_recorded_by: Optional[str] = None
    rentals_paid: int = 0
    lease_start: Optional[date] = None
    closing_reason: Optional[str] = None

    @property
    def financed_amount(self) -> Decimal:
        return self.asset.purchase_price - self.terms.down_payment

    def latest(self, doc_type: str) -> Optional[Document]:
        versions = self.documents.get(doc_type)
        return versions[-1] if versions else None

    def log(self, actor: str, action: str, detail: str = "") -> None:
        self.audit.append(AuditEvent(datetime.now(timezone.utc), actor, action, detail))
