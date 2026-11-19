"""Unit tests for the request schemas."""

import pytest
from pydantic import ValidationError

from app.schemas import CampaignCreate, OfferAdd


def test_geo_is_normalized() -> None:
    model = CampaignCreate(name="c", geo="us", offer_id=1)
    assert model.geo == "US"


def test_geo_rejects_non_letters() -> None:
    with pytest.raises(ValidationError):
        CampaignCreate(name="c", geo="U1", offer_id=1)


def test_geo_rejects_wrong_length() -> None:
    with pytest.raises(ValidationError):
        CampaignCreate(name="c", geo="USA", offer_id=1)


def test_geo_rejects_unknown_country() -> None:
    with pytest.raises(ValidationError):
        CampaignCreate(name="c", geo="QQ", offer_id=1)


def test_name_is_required() -> None:
    with pytest.raises(ValidationError):
        CampaignCreate.model_validate({"geo": "US", "offer_id": 1})


def test_offer_id_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        OfferAdd(offer_id=0)
