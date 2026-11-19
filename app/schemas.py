"""Pydantic models for request bodies and endpoint responses."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from .countries import ISO_ALPHA2


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    geo: str = Field(
        min_length=2, max_length=2, description="ISO country code, e.g. US"
    )
    offer_id: int = Field(gt=0)
    # Optional overrides; the first dictionary entry is used by default
    domain_id: int | None = None
    group_id: int | None = None
    source_id: int | None = None

    @field_validator("geo")
    @classmethod
    def upper_geo(cls, v: str) -> str:
        v = v.strip().upper()
        if not v.isalpha():
            raise ValueError("geo должен состоять из двух букв")
        if v not in ISO_ALPHA2:
            raise ValueError("неизвестный код страны ISO-3166")
        return v


class OfferAdd(BaseModel):
    offer_id: int = Field(gt=0)
    stream_id: int | None = None


class DictItem(BaseModel):
    """One entry of a Keitaro dictionary (domain, group, source, offer)."""

    id: int
    name: str


class Dictionaries(BaseModel):
    """Dictionary payloads that feed the creation form."""

    domains: list[DictItem]
    groups: list[DictItem]
    sources: list[DictItem]
    offers: list[DictItem]


class CampaignCreated(BaseModel):
    """Confirmation that a campaign now exists in Keitaro."""

    id: int
    name: str
    domain_id: int
    group_id: int
    source_id: int


class CampaignListItem(BaseModel):
    """A campaign created through the creator, as listed for the editor."""

    id: int
    name: str
    geo: str
    created_at: datetime


class OfferStats(BaseModel):
    """Per-offer numbers exactly as Keitaro reports them."""

    clicks: int | float | str | None
    unique_clicks: int | float | str | None
    conversions: int | float | str | None
    revenue: int | float | str | None
    cost: int | float | str | None
    profit: int | float | str | None


class OfferView(BaseModel):
    """An offer inside a stream, with its share and statistics."""

    offer_id: int
    name: str
    share: int | float | str | None
    state: str | None
    stats: OfferStats


class StreamView(BaseModel):
    """A campaign stream with its offers."""

    id: int
    name: str | None
    schema_: str | None = Field(default=None, alias="schema")
    offers: list[OfferView]


class CampaignView(BaseModel):
    """Full campaign payload returned by the editor."""

    id: int
    name: str
    streams: list[StreamView]
    stats_error: str | None = None
