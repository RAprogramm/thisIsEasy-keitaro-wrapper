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
