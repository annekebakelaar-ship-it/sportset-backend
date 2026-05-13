"""
backend/models/orm_models.py
----------------------------
SQLAlchemy ORM-modellen voor YouCaps.

Tabellen:
  supplements          — supplement-producten (product-catalogus)
  ingredients          — ingrediënten per supplement
  contra_indications   — contra-indicaties per supplement
  users                — gebruikersaccounts
  user_medications     — medicijnen per gebruiker (Art. 9 bijzondere persoonsgegevens)
  user_allergies       — allergieën per gebruiker  (Art. 9 bijzondere persoonsgegevens)
  audit_log            — append-only audit trail (IEC 62304 traceability)

AVG-noot:
  user_medications en user_allergies zijn bijzondere persoonsgegevens (AVG Art. 9).
  Encryptie at rest en toegangsbeperking zijn verplicht vóór productie-gebruik.
  Retentiebeleid: zie docs/phase1/01_discovery_and_risk_analysis.md §4B.2.
"""

from __future__ import annotations



import uuid

def _uuid() -> str:
    return str(uuid.uuid4())

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.database import Base


# ---------------------------------------------------------------------------
# Hulpfunctie: UTC-timestamp
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Supplement
# ---------------------------------------------------------------------------

class SupplementORM(Base):
    """
    Supplement-product in de catalogus.

    Uniek op (name, brand, dosage) — duplicaten zoals de Visolie-bug worden hierdoor voorkomen.
    """
    __tablename__ = "supplements"
    __table_args__ = (
        UniqueConstraint("name", "brand", "dosage", name="uq_supplement_name_brand_dosage"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
        comment="UUID primary key"
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    brand: Mapped[str | None] = mapped_column(String(200), nullable=True)
    dosage: Mapped[str] = mapped_column(String(100), nullable=False)
    product_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="Tablet, Capsule, Poeder, etc."
    )

    # AI-logica velden
    optimal_timing: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_benefit: Mapped[str | None] = mapped_column(Text, nullable=True)
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Data-kwaliteit
    source: Mapped[str] = mapped_column(
        String(100), default="manual",
        comment="Herkomst: manual | scan | openfoodfacts | api"
    )
    ai_generated: Mapped[bool] = mapped_column(
        Boolean, default=False,
        comment="True als AI (Claude) dit record heeft aangemaakt — nog niet menselijk geverifieerd"
    )
    verified: Mapped[bool] = mapped_column(
        Boolean, default=False,
        comment="True als een mens dit record heeft geverifieerd"
    )

    # Tijdstempels (audit trail)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    # Relaties
    ingredients: Mapped[list[IngredientORM]] = relationship(
        "IngredientORM", back_populates="supplement", cascade="all, delete-orphan"
    )
    contra_indications: Mapped[list[ContraIndicationORM]] = relationship(
        "ContraIndicationORM", back_populates="supplement", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Supplement id={self.id!r} name={self.name!r} brand={self.brand!r}>"


# ---------------------------------------------------------------------------
# Ingredient
# ---------------------------------------------------------------------------

class IngredientORM(Base):
    """Één ingrediënt van een supplement."""
    __tablename__ = "ingredients"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    supplement_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("supplements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    amount: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    supplement: Mapped[SupplementORM] = relationship("SupplementORM", back_populates="ingredients")

    def __repr__(self) -> str:
        return f"<Ingredient id={self.id!r} name={self.name!r} amount={self.amount!r}>"


# ---------------------------------------------------------------------------
# ContraIndication
# ---------------------------------------------------------------------------

class ContraIndicationORM(Base):
    """
    Contra-indicatie van een supplement met een medicijn of aandoening.

    BELANGRIJK (R-003 mitigatie):
      ai_generated=True  → gegenereerd door Claude; NOG NIET medisch geverifieerd.
      verified=False      → mag niet als authoritative bron worden gebruikt in Safety Engine.

    De Safety Engine in backend/services/safety_engine.py filtert op verified=True.
    """
    __tablename__ = "contra_indications"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    supplement_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("supplements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    medication_or_condition: Mapped[str] = mapped_column(
        String(500), nullable=False, index=True,
        comment="Naam van medicijn, medicijnklasse of aandoening"
    )
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, default="medium",
        comment="low | medium | high | critical"
    )
    mechanism: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Farmacologisch mechanisme")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_level: Mapped[str | None] = mapped_column(
        String(5), nullable=True,
        comment="GRADE: A=hoog, B=matig, C=laag, D=expert-opinie"
    )
    source: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Bronvermelding")

    # Data-kwaliteit vlaggen (R-003 mitigatie)
    ai_generated: Mapped[bool] = mapped_column(
        Boolean, default=False,
        comment="True als Claude deze contra-indicatie heeft gegenereerd"
    )
    verified: Mapped[bool] = mapped_column(
        Boolean, default=False,
        comment="True als een mens (arts/apotheker) dit heeft geverifieerd"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    supplement: Mapped[SupplementORM] = relationship(
        "SupplementORM", back_populates="contra_indications"
    )

    def __repr__(self) -> str:
        return (
            f"<ContraIndication id={self.id!r} "
            f"target={self.medication_or_condition!r} severity={self.severity!r} "
            f"verified={self.verified}>"
        )


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class UserORM(Base):
    """
    Gebruikersaccount.

    AVG Art. 4 lid 1 — persoonsgegeven.
    Wachtwoord wordt opgeslagen als bcrypt-hash (via passlib).
    """
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(
        String(254), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Soft-delete — AVG Art. 17 recht op wissing"
    )

    # Relaties — bijzondere persoonsgegevens (AVG Art. 9)
    medications: Mapped[list[UserMedicationORM]] = relationship(
        "UserMedicationORM", back_populates="user", cascade="all, delete-orphan"
    )
    allergies: Mapped[list[UserAllergyORM]] = relationship(
        "UserAllergyORM", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id!r} email={self.email!r}>"
    # Magic link auth (stap 2)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    magic_links: Mapped[list["MagicLinkTokenORM"]] = relationship(
        "MagicLinkTokenORM", back_populates="user", cascade="all, delete-orphan"
    )
    scans: Mapped[list["UserScanORM"]] = relationship(
        "UserScanORM", back_populates="user", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# UserMedication — BIJZONDER PERSOONSGEGEVEN (AVG Art. 9)
# ---------------------------------------------------------------------------

class UserMedicationORM(Base):
    """
    Medicijn dat een gebruiker gebruikt.

    ⚠️ BIJZONDER PERSOONSGEGEVEN (AVG Art. 9 — gezondheidsdata).
    Encryptie at rest verplicht vóór productie.
    Retentie: actief gebruik + 1 jaar na laatste login.
    """
    __tablename__ = "user_medications"
    __table_args__ = (
        Index("ix_user_medications_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(
        String(300), nullable=False,
        comment="Vrije-tekst medicijnnaam (bijv. 'Warfarine', 'Bloedverdunners')"
    )
    atc_code: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="ATC-code voor gestandaardiseerde interactiecheck (toekomstig)"
    )
    start_date: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="YYYY-MM-DD")
    end_date: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="YYYY-MM-DD")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    user: Mapped[UserORM] = relationship("UserORM", back_populates="medications")

    def __repr__(self) -> str:
        return f"<UserMedication user={self.user_id!r} name={self.name!r}>"


# ---------------------------------------------------------------------------
# UserAllergy — BIJZONDER PERSOONSGEGEVEN (AVG Art. 9)
# ---------------------------------------------------------------------------

class UserAllergyORM(Base):
    """
    Allergie van een gebruiker.

    ⚠️ BIJZONDER PERSOONSGEGEVEN (AVG Art. 9 — gezondheidsdata).
    Encryptie at rest verplicht vóór productie.

    Dit model löst R-001 (allergie-check afwezig) op architecturaal niveau:
    user.allergies is nu een eersteklas entiteit die door de Safety Engine
    wordt gecheckt naast user.medications.
    """
    __tablename__ = "user_allergies"
    __table_args__ = (
        Index("ix_user_allergies_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    allergen: Mapped[str] = mapped_column(
        String(300), nullable=False,
        comment="Vrije-tekst allergeennaam (bijv. 'Vis', 'Gluten', 'Schaaldieren')"
    )
    severity: Mapped[str] = mapped_column(
        String(20), default="unknown",
        comment="mild | moderate | severe | anaphylactic | unknown"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    user: Mapped[UserORM] = relationship("UserORM", back_populates="allergies")

    def __repr__(self) -> str:
        return f"<UserAllergy user={self.user_id!r} allergen={self.allergen!r}>"


# ---------------------------------------------------------------------------
# AuditLog — append-only, IEC 62304 traceability
# ---------------------------------------------------------------------------

class AuditLogORM(Base):
    """
    Append-only audit log voor alle medisch-relevante acties.

    IEC 62304 §5.5.3 vereist traceability van alle software-operaties die
    de veiligheid van de patiënt kunnen beïnvloeden.

    Hash-chaining (prev_hash → payload_hash) maakt tamper-evidence mogelijk:
    als een log-entry wordt gewijzigd, breekt de keten aantoonbaar.

    NOOIT verwijderen of updaten van log-entries. Alleen INSERT is toegestaan.
    """
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_user_timestamp", "user_id", "timestamp"),
        Index("ix_audit_log_action", "action"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True,
        comment="Null voor anonieme aanvragen"
    )
    action: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="bijv. scan_label | check_safety | get_advice | create_supplement"
    )
    resource_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="bijv. supplement | user | safety_check"
    )
    resource_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True,
        comment="ID van het betrokken object"
    )
    payload_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="SHA-256 hash van de request-payload"
    )
    response_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="SHA-256 hash van de response"
    )
    prev_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="SHA-256 hash van de vorige log-entry (hash-chain voor tamper-evidence)"
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status_code: Mapped[int | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id!r} action={self.action!r} user={self.user_id!r}>"


# ---------------------------------------------------------------------------
# Scan — Vision Scanner output (Fase 3)
# ---------------------------------------------------------------------------

class ScanORM(Base):
    """
    Eén foto-scan met de daaruit geëxtraheerde structuur.

    Bewust géén opslag van de afbeelding zelf (privacy + storage cost):
    we bewaren alleen de SHA-256 hash van de geprocesste bytes, plus de
    rauwe AI-extractie en metadata.

    De `raw_extraction`-kolom bevat het volledige JSON-object dat door
    Claude Vision is geretourneerd, gevalideerd door ScanExtraction.
    Dit maakt later her-matchen of audits mogelijk zonder nieuwe AI-call.
    """
    __tablename__ = "scans"
    __table_args__ = (
        Index("ix_scans_user_created", "user_id", "created_at"),
        Index("ix_scans_image_hash", "image_hash"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="Null voor anonieme scans (Fase 3 nog zonder auth)"
    )

    # Productinfo (gedupliceerd uit raw_extraction voor snelle queries/UI)
    product_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(200), nullable=True)
    overall_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    # AI-trace
    raw_extraction: Mapped[dict] = mapped_column(
        JSON, nullable=False,
        comment="Volledige ScanExtraction als dict — primair brondocument voor analytics"
    )
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    ai_attempts: Mapped[int] = mapped_column(Integer, default=1)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    # Image-metadata (geen pixels op disk!)
    image_hash: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="SHA-256 van de geprocesste JPEG-bytes"
    )
    image_bytes: Mapped[int] = mapped_column(Integer, default=0)
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )

    def __repr__(self) -> str:
        return (
            f"<Scan id={self.id!r} product={self.product_name!r} "
            f"conf={self.overall_confidence:.2f}>"
        )
class MagicLinkTokenORM(Base):
    """
    Eenmalig token voor magic-link login. Gegenereerd bij /auth/request-link,
    geconsumeerd bij /auth/verify. Kan ook bestaan zonder bestaande user
    (eerste-keer signup) — in dat geval wordt user_id later ingevuld bij verify.
    """
    __tablename__ = "magic_link_tokens"

    id = Column(String, primary_key=True, default=_uuid)
    # SHA-256 hash van het token, niet het token zelf
    token_hash = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("UserORM", back_populates="magic_links")



class UserScanORM(Base):
    """
    Eén bewaarde scan per gebruiker. Het hele Supplement-object wordt
    als JSON opgeslagen (denormalised) zodat we niet aan iedere wijziging
    in supplement-schema migrations vasthangen.
    """
    __tablename__ = "user_scans"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    supplement = Column(JSON, nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)

    user = relationship("UserORM", back_populates="scans")


    
