from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class Category(str, Enum):
    handbags = "handbags"
    watches = "watches"
    cars = "cars"
    wine = "wine"
    cards = "cards"
    memorabilia = "memorabilia"
    comics = "comics"
    books = "books"
    fossils = "fossils"
    natural_history = "natural_history"
    art = "art"
    instruments = "instruments"
    precious_minerals = "precious minerals"
    coins = "coins"
    other = "other"


class SourceQuality(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class Asset(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    asset_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: Category
    subcategory: str = "uncategorized"
    issuer_cik: Optional[str] = None
    series_name: Optional[str] = None
    offering_date: Optional[date] = None
    offering_price: float = Field(gt=0)
    shares: int = Field(gt=0)
    market_cap_usd: Optional[float] = Field(default=None, gt=0)
    last_price_usd: Optional[float] = Field(default=None, gt=0)
    source_url: Optional[str] = None
    source_confidence: float = Field(ge=0, le=1)
    rarity_score: float = Field(default=0.5, ge=0, le=1)
    status: str = "active"
    trading_state: Optional[str] = None
    lifecycle_event_type: Optional[str] = None
    lifecycle_event_status: Optional[str] = None
    lifecycle_event_date: Optional[date] = None
    status_updated_at: Optional[str] = None
    buyout_offer_date: Optional[date] = None
    buyout_offer_price_per_share: Optional[float] = Field(default=None, gt=0)
    buyout_offer_total_value: Optional[float] = Field(default=None, gt=0)
    buyout_reference_price: Optional[float] = Field(default=None, gt=0)
    buyout_reference_price_date: Optional[date] = None
    buyout_premium_pct: Optional[float] = None
    buyout_vote_yes_pct: Optional[float] = Field(default=None, ge=0, le=100)
    buyout_vote_no_pct: Optional[float] = Field(default=None, ge=0, le=100)
    buyout_vote_advisory_pct: Optional[float] = Field(default=None, ge=0, le=100)
    buyout_vote_as_of: Optional[str] = None
    buyout_vote_provisional: Optional[bool] = None
    buyout_notes: Optional[str] = None
    notes: Optional[str] = None
    underlying_collectible: Optional[str] = None
    significance: Optional[str] = None
    publisher: Optional[str] = None
    publication_year: Optional[int] = None
    issue_number: Optional[int] = None
    grade: Optional[str] = None


class RallySnapshot(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    date: date
    asset_id: str
    ticker: str
    price: float = Field(gt=0)
    bid: Optional[float] = Field(default=None, gt=0)
    ask: Optional[float] = Field(default=None, gt=0)
    volume: float = Field(default=0, ge=0)
    market_cap_usd: Optional[float] = Field(default=None, gt=0)
    source: str
    source_confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def ask_not_below_bid(self) -> "RallySnapshot":
        if self.bid is not None and self.ask is not None and self.ask < self.bid:
            raise ValueError("ask must be greater than or equal to bid")
        return self


class ComparableSale(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    comp_id: str = Field(min_length=1)
    category: Category
    subcategory: str
    asset_id: Optional[str] = None
    source: str = Field(min_length=1)
    source_url: Optional[str] = None
    date: date
    price_usd: float = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    condition: Optional[str] = None
    exactness_score: float = Field(ge=0, le=1)
    source_confidence: float = Field(ge=0, le=1)
    price_type: str = "realized_with_premium"
    source_access: str = "public_page"
    venue: Optional[str] = None
    auction_name: Optional[str] = None
    lot_id: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    reference: Optional[str] = None
    size: Optional[str] = None
    material: Optional[str] = None
    color: Optional[str] = None
    hardware: Optional[str] = None
    year: Optional[int] = Field(default=None, ge=0)
    title: Optional[str] = None
    auction_url: Optional[str] = None
    lot_url: Optional[str] = None
    raw_text_path: Optional[str] = None
    confidence_score: Optional[float] = Field(default=None, ge=0, le=1)
    estimate_low_usd: Optional[float] = Field(default=None, ge=0)
    estimate_high_usd: Optional[float] = Field(default=None, ge=0)
    buyer_premium_included: Optional[bool] = None
    notes: Optional[str] = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class MarketIndexObservation(BaseModel):
    category: Category
    source: str = Field(min_length=1)
    source_url: Optional[str] = None
    date: date
    brand: str = Field(min_length=1)
    model: Optional[str] = None
    reference: Optional[str] = None
    metric_name: str = Field(min_length=1)
    metric_value: float
    currency: str = Field(default="USD", min_length=3, max_length=3)
    source_access: str = "public_page"
    source_confidence: float = Field(ge=0, le=1)
    notes: Optional[str] = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class SecFilingSeries(BaseModel):
    series_id: str = Field(min_length=1)
    cik: str = Field(min_length=1)
    accession_number: str = Field(min_length=1)
    filing_type: str = Field(min_length=1)
    filing_date: date
    filing_url: str
    series_name: Optional[str] = None
    asset_name: Optional[str] = None
    offering_price: Optional[float] = Field(default=None, gt=0)
    shares: Optional[int] = Field(default=None, gt=0)
    acquisition_cost: Optional[float] = Field(default=None, ge=0)
    offering_expenses: Optional[float] = Field(default=None, ge=0)
    status: Optional[str] = None
    source_confidence: float = Field(default=0.5, ge=0, le=1)


class ExitEvent(BaseModel):
    exit_id: str = Field(min_length=1)
    asset_id: Optional[str] = None
    ticker: Optional[str] = None
    series_name: Optional[str] = None
    exit_type: str = "other"
    exit_status: str = "settled"
    sale_price: Optional[float] = Field(default=None, gt=0)
    sale_date: Optional[date] = None
    exit_announcement_date: Optional[date] = None
    last_trading_date: Optional[date] = None
    exit_valuation_date: Optional[date] = None
    exit_effective_date: Optional[date] = None
    settlement_date: Optional[date] = None
    exit_price_per_share: Optional[float] = Field(default=None, gt=0)
    exit_total_value: Optional[float] = Field(default=None, gt=0)
    shares_at_exit: Optional[float] = Field(default=None, gt=0)
    realized_return: Optional[float] = None
    payout_source: Optional[str] = None
    source_url: Optional[str] = None
    source_reference: Optional[str] = None
    notes: Optional[str] = None
    is_confirmed: bool = True
    data_quality_flag: Optional[str] = None
    source_confidence: float = Field(default=0.5, ge=0, le=1)


class CategoryMetadata(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    category: Category
    display_name: str
    category_momentum_score: float = Field(default=0.5, ge=0, le=1)
    condition_modifier: float = Field(default=1.0, gt=0)
    notes: Optional[str] = None


class PriceObservation(BaseModel):
    date: date
    asset_id: str
    bid: Optional[float] = Field(default=None, gt=0)
    ask: Optional[float] = Field(default=None, gt=0)
    last: float = Field(gt=0)
    volume: float = Field(default=0, ge=0)
    market_cap_usd: Optional[float] = Field(default=None, gt=0)
    source: str

    @model_validator(mode="after")
    def ask_not_below_bid(self) -> "PriceObservation":
        if self.bid is not None and self.ask is not None and self.ask < self.bid:
            raise ValueError("ask must be greater than or equal to bid")
        return self


class LiquidityMetrics(BaseModel):
    asset_id: str
    bid_ask_spread_pct: Optional[float] = None
    turnover: float = Field(ge=0)
    days_since_last_trade: int = Field(ge=0)
    days_with_zero_trades: int = Field(ge=0)
    realized_volatility: float = Field(ge=0)
    max_drawdown: float = Field(le=0)
    return_since_offering: Optional[float] = None
    stale_mark_flag: bool


class NavEstimate(BaseModel):
    asset_id: str
    estimated_nav_usd: float = Field(gt=0)
    nav_low_usd: float = Field(gt=0)
    nav_high_usd: float = Field(gt=0)
    nav_confidence: float = Field(ge=0, le=1)
    premium_discount_pct: Optional[float] = None
    discount_to_secondary_nav: Optional[float] = None
    valuation_notes: str
