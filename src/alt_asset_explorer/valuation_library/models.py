from __future__ import annotations
from datetime import date
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

Category = Literal['fossils','watches','books','handbags','wine and whiskey']
WorkflowStatus = Literal['intake_missing','factors_ready','research_ready','valuation_ready','report_ready','published','needs_review','stale','valuation_error','error']
SaleStatus = Literal['sold','unsold','passed','withdrawn','unknown']
Currency = Literal['USD','EUR','GBP','CHF','HKD']
ValuationStatus = Literal['completed','completed_with_limitations','provisional','manual_review_required','insufficient_evidence','error','needs_review']

class FlexibleModel(BaseModel):
    model_config = ConfigDict(extra='allow')

class QuarterlyPriceObservation(FlexibleModel):
    date: date
    share_price_usd: float | None = Field(default=None, ge=0)
    market_value_usd: float | None = Field(default=None, ge=0)

class RallyData(FlexibleModel):
    asset_id: str | None = None
    ticker: str | None = None
    asset_name: str | None = None
    category: str | None = None
    subcategory: str | None = None
    launch_date: date | None = None
    initial_offering_value_usd: float | None = Field(default=None, ge=0)
    shares_offered: float | None = Field(default=None, ge=0)
    shares_outstanding: float | None = Field(default=None, ge=0)
    initial_share_price_usd: float | None = Field(default=None, ge=0)
    latest_share_price_usd: float | None = Field(default=None, ge=0)
    latest_market_value_usd: float | None = Field(default=None, ge=0)
    last_trade_date: date | None = None
    asset_status: str | None = None
    quarterly_price_history: list[QuarterlyPriceObservation] = Field(default_factory=list)
    quarterly_price_history_source: str | None = None
    source_registry_path: str | None = None
    warnings: list[str] = Field(default_factory=list)

class Factors(FlexibleModel):
    schema_version: str = '1.0'
    asset_id: str = Field(min_length=1)
    rally_symbol: str | None = None
    asset_name: str
    category: Category
    subcategory: str | None = None
    rally_data: RallyData = Field(default_factory=RallyData)
    identity: dict[str, Any] = Field(default_factory=dict)
    category_factors: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    field_provenance: dict[str, Any] = Field(default_factory=dict)
    merge_warnings: list[dict[str, Any]] = Field(default_factory=list)
    condition: dict[str, Any] = Field(default_factory=dict)
    source_notes: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    observed_facts: dict[str, Any] = Field(default_factory=dict)
    derived_scores: dict[str, float] = Field(default_factory=dict)
    analyst_judgments: dict[str, Any] = Field(default_factory=dict)

class SimilarityScores(FlexibleModel):
    identity_similarity: float | None = Field(default=None, ge=0, le=1)
    condition_similarity: float | None = Field(default=None, ge=0, le=1)
    provenance_similarity: float | None = Field(default=None, ge=0, le=1)
    presentation_similarity: float | None = Field(default=None, ge=0, le=1)

class ComparableSale(FlexibleModel):
    comparable_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    sale_date: date | None = None
    venue: str | None = None
    sale_status: SaleStatus = 'unknown'
    currency: Currency = 'USD'
    reported_price: float | None = Field(default=None, gt=0)
    buyers_premium_included: bool | None = None
    price_usd: float | None = Field(default=None, gt=0)
    price_usd_at_sale: float | None = Field(default=None, gt=0)
    fx_rate_to_usd: float | None = Field(default=None, gt=0)
    eligible_for_official_valuation: bool | None = None
    specimen_characteristics: dict[str, Any] = Field(default_factory=dict)
    similarity_scores: SimilarityScores = Field(default_factory=SimilarityScores)
    overall_similarity: float | None = Field(default=None, ge=0, le=1)
    evidence_quality: float | None = Field(default=None, ge=0, le=1)
    source_url: HttpUrl | str | None = None
    source_accessed: date | None = None
    verified: bool = False
    notes: str = ''
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def flag_questionable(self):
        today = date.today()
        warnings = list(self.warnings)
        if self.price_usd is None and self.price_usd_at_sale is not None:
            self.price_usd = self.price_usd_at_sale
        if self.sale_date and self.sale_date > today: warnings.append('future_sale_date')
        if not self.source_url: warnings.append('missing_source_reference')
        if self.sale_status == 'sold' and self.price_usd is None and self.reported_price is None: warnings.append('sold_without_price')
        if self.sale_status == 'sold' and self.buyers_premium_included is None: warnings.append('premium_treatment_unknown')
        if self.currency != 'USD' and self.price_usd is None and self.fx_rate_to_usd is None: warnings.append('currency_conversion_unavailable')
        self.warnings = sorted(set(warnings))
        return self

class Research(FlexibleModel):
    schema_version: str = '1.0'
    asset_id: str = Field(min_length=1)
    research_date: date
    comparable_sales: list[ComparableSale] = Field(default_factory=list)
    market_context: dict[str, Any] = Field(default_factory=dict)
    supply_factors: dict[str, Any] = Field(default_factory=dict)
    demand_factors: dict[str, Any] = Field(default_factory=dict)
    liquidity_observations: dict[str, Any] = Field(default_factory=dict)
    legal_regulatory_considerations: list[str] = Field(default_factory=list)
    valuation_assumptions: dict[str, Any] = Field(default_factory=dict)
    research_limitations: list[str] = Field(default_factory=list)
    source_ledger: list[dict[str, Any]] = Field(default_factory=list)
    analyst_notes: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def duplicates_and_dates(self):
        ids=[c.comparable_id for c in self.comparable_sales]
        if len(ids)!=len(set(ids)): raise ValueError('duplicate comparable_id values are not allowed')
        if self.research_date > date.today(): raise ValueError('research_date cannot be in the future')
        return self

class ValuationResults(FlexibleModel):
    conservative_value_usd: float | None = None
    base_value_usd: float | None = None
    optimistic_value_usd: float | None = None
    confidence_score: float = Field(ge=0, le=1)
    official_value_available: bool = False

class Valuation(FlexibleModel):
    schema_version: str = '1.0'
    asset_id: str
    valuation_date: date
    valuation_status: ValuationStatus
    methodology_version: str
    category_model_version: str
    results: ValuationResults
    market_comparison: dict[str, Any] = Field(default_factory=dict)
    comparables_used: list[dict[str, Any]] = Field(default_factory=list)
    comparable_diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    diagnostic_table: list[dict[str, Any]] = Field(default_factory=list)
    calculation_summary: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    calculation_trace: list[dict[str, Any]] = Field(default_factory=list)

class Manifest(FlexibleModel):
    schema_version: str = '1.0'
    asset_id: str
    display_name: str | None = None
    rally_match: dict[str, Any] | None = None
    files_present: dict[str, bool] = Field(default_factory=dict)
    schema_versions: dict[str, str] = Field(default_factory=dict)
    methodology_version: str | None = None
    research_date: date | None = None
    valuation_date: date | None = None
    report_date: date | None = None
    publication_status: WorkflowStatus = 'intake_missing'
    validation_status: str = 'unknown'
    missing_required_files: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    last_modified: dict[str, str] = Field(default_factory=dict)
