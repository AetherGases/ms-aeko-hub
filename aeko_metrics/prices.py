"""Load and resolve USD rates from AEKO_MODEL_PRICES and configured model names."""

from __future__ import annotations

import json
import os


def _normalize_model_id(model: str) -> str:
    """Normalize a provider model id to its trailing name."""
    text = model.strip().lower()
    if text.startswith("models/"):
        text = text[len("models/") :]
    return text.split("/")[-1]


def _rates_from_entry(entry: dict | None) -> tuple[float, float]:
    """Read input and output USD-per-million rates from a price row."""
    if not entry:
        return (0.0, 0.0)
    input_rate = float(entry.get("input_per_million", 0) or 0)
    output_rate = float(entry.get("output_per_million", 0) or 0)
    return (input_rate, output_rate)


def lookup_rates(model: str, prices: dict) -> tuple[float, float]:
    """Resolve input/output USD-per-million rates for a provider-reported model id."""
    raw = model.strip()
    if not raw:
        return (0.0, 0.0)

    for candidate in (raw, _normalize_model_id(raw)):
        if candidate in prices:
            return _rates_from_entry(prices[candidate])

    norm_model = _normalize_model_id(raw)
    best_key: str | None = None
    best_len = 0
    for key, entry in prices.items():
        norm_key = _normalize_model_id(key)
        if norm_key in norm_model or norm_model in norm_key:
            if len(norm_key) > best_len:
                best_len = len(norm_key)
                best_key = key
    if best_key is not None:
        return _rates_from_entry(prices[best_key])

    return (0.0, 0.0)


def enrich_prices(prices: dict) -> dict:
    """Copy table entries onto AEKO_FAST_MODEL / AEKO_SLOW_MODEL when names differ."""
    enriched = dict(prices)
    for env_key in ("AEKO_FAST_MODEL", "AEKO_SLOW_MODEL"):
        model = os.getenv(env_key, "").strip()
        if not model or model in enriched:
            continue
        in_rate, out_rate = lookup_rates(model, prices)
        if in_rate or out_rate:
            enriched[model] = {
                "input_per_million": in_rate,
                "output_per_million": out_rate,
            }
            continue
        for key, entry in prices.items():
            norm_key = _normalize_model_id(key)
            norm_model = _normalize_model_id(model)
            if (
                norm_key == norm_model
                or norm_key in norm_model
                or norm_model in norm_key
                or ("flash-lite" in norm_model and "flash-lite" in norm_key)
            ):
                enriched[model] = dict(entry)
                break
    return enriched


def load_prices() -> dict:
    """Parse AEKO_MODEL_PRICES and add aliases for configured fast/slow models."""
    raw = os.environ.get("AEKO_MODEL_PRICES", "").strip() or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return enrich_prices(parsed)
