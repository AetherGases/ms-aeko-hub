"""Verify AEKO_MODEL_PRICES loading and model-id resolution."""

import json

import pytest

from aeko_metrics.prices import enrich_prices, load_prices, lookup_rates


PRICES = {
    "gemini-3.5-flash": {"input_per_million": 0.15, "output_per_million": 0.60},
    "gemini-3.1-flash-lite": {"input_per_million": 0.025, "output_per_million": 0.15},
}


def test_lookup_rates_returns_zero_for_blank_model():
    assert lookup_rates("  ", PRICES) == (0.0, 0.0)


def test_lookup_rates_matches_provider_model_path():
    assert lookup_rates("models/gemini-3.5-flash", PRICES) == (0.15, 0.60)


def test_lookup_rates_matches_normalized_trailing_segment():
    assert lookup_rates("providers/gemini-3.5-flash", PRICES) == (0.15, 0.60)


def test_lookup_rates_resolves_configured_model_alias_in_table():
    table = {
        **PRICES,
        "custom-fast": {"input_per_million": 1.0, "output_per_million": 2.0},
    }
    assert lookup_rates("models/custom-fast", table) == (1.0, 2.0)


def test_lookup_rates_returns_zero_for_unknown_model():
    assert lookup_rates("mystery", PRICES) == (0.0, 0.0)


def test_enrich_prices_aliases_configured_fast_model(monkeypatch):
    monkeypatch.setenv("AEKO_FAST_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.delenv("AEKO_SLOW_MODEL", raising=False)
    flash_lite_only = {"gemini-3.1-flash-lite": PRICES["gemini-3.1-flash-lite"]}
    enriched = enrich_prices(flash_lite_only)
    assert enriched["gemini-3.5-flash-lite"] == flash_lite_only["gemini-3.1-flash-lite"]


def test_enrich_prices_skips_when_model_already_present(monkeypatch):
    monkeypatch.setenv("AEKO_FAST_MODEL", "gemini-3.5-flash")
    enriched = enrich_prices(PRICES)
    assert enriched == PRICES


def test_enrich_prices_adds_env_model_when_lookup_resolves_rates(monkeypatch):
    monkeypatch.setenv("AEKO_FAST_MODEL", "providers/gemini-3.5-flash")
    monkeypatch.delenv("AEKO_SLOW_MODEL", raising=False)
    enriched = enrich_prices(PRICES)
    assert enriched["providers/gemini-3.5-flash"]["input_per_million"] == 0.15


def test_load_prices_parses_env_json(monkeypatch):
    monkeypatch.setenv(
        "AEKO_MODEL_PRICES",
        json.dumps(PRICES),
    )
    assert load_prices()["gemini-3.5-flash"]["input_per_million"] == 0.15


def test_load_prices_returns_empty_on_invalid_json(monkeypatch):
    monkeypatch.setenv("AEKO_MODEL_PRICES", "{not-json")
    assert load_prices() == {}


def test_load_prices_returns_empty_when_not_a_dict(monkeypatch):
    monkeypatch.setenv("AEKO_MODEL_PRICES", json.dumps([1, 2]))
    assert load_prices() == {}


def test_lookup_rates_treats_null_price_entry_as_zero():
    assert lookup_rates("priced", {"priced": None}) == (0.0, 0.0)


def test_lookup_rates_picks_the_longest_fuzzy_price_key():
    table = {
        "vendor/gemini-3.5-flash": {"input_per_million": 0.15, "output_per_million": 0.60},
        "vendor/gemini-3.5-flash-lite": {"input_per_million": 0.025, "output_per_million": 0.15},
    }
    assert lookup_rates("gemini-3.5-flash-lite", table) == (0.025, 0.15)


