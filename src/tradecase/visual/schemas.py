from typing import Literal

from pydantic import Field, field_validator

from tradecase.platform.contracts import Input

Intent = Literal[
    "product_comparison", "oem_preview", "packaging_preview", "spec_illustration", "odm_concept", "buyer_presentation"
]


class ProductInput(Input):
    sku: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    dimensions: str = Field(default="", max_length=1000)
    material: str = Field(default="", max_length=1000)
    colors: list[str] = Field(default_factory=list, max_length=30)
    structure: list[str] = Field(default_factory=list, max_length=30)
    customization: list[str] = Field(default_factory=list, max_length=30)
    source: str = Field(min_length=1, max_length=2000)
    fact_status: Literal["verified", "supplier_claim", "unverified", "concept"] = "unverified"
    external_use: bool = False
    expected_version: int | None = Field(default=None, ge=1)


class PlanInput(Input):
    product_id: str = Field(min_length=1, max_length=64)
    intent: Intent
    requirement: str = Field(min_length=1, max_length=2000)
    source_asset_ids: list[str] = Field(default_factory=list, max_length=16)
    evidence_refs: list[str] = Field(default_factory=list, max_length=16)
    allowed_changes: list[
        Literal[
            "authorized_logo",
            "color",
            "background",
            "packaging",
            "layout",
            "product_structure",
            "material",
            "dimensions",
        ]
    ] = Field(default_factory=list, max_length=16)
    preserve: list[str] = Field(default_factory=lambda: ["product_structure", "dimensions"], max_length=16)
    variants: int = Field(default=1, ge=1, le=8)
    budget_usd: float = Field(default=1, ge=0, le=100, allow_inf_nan=False)
    concept: bool = False

    @field_validator("requirement")
    @classmethod
    def minimize(cls, value):
        import re

        if re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b(?:\+?\d[\d ()-]{8,}\d)\b", value):
            raise ValueError("Visual requirement must not include buyer contact details")
        return value


class VersionInput(Input):
    version: int = Field(ge=1)


class ApprovePlan(VersionInput):
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    data_processing_authorized: bool = False


class AssetReview(VersionInput):
    asset_id: str
    asset_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision: Literal["approve", "reject"]
    comment: str = Field(default="", max_length=3000)


class Revise(VersionInput):
    plan: PlanInput


class Attach(VersionInput):
    asset_ids: list[str] = Field(min_length=1, max_length=8)
    case_version: int = Field(ge=1)
    update_draft: bool = True
