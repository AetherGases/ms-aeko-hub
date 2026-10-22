"""Compute USD cost from agent token usage and a per-model price table."""

from aeko_metrics.prices import enrich_prices, lookup_rates


def _rates_for_agent_llm(llm: str, prices: dict) -> tuple[float, float]:
    """Resolve input and output rates for a comma-separated LLM field."""
    parts = [piece.strip() for piece in llm.split(",") if piece.strip()]
    if not parts:
        return lookup_rates(llm, prices)
    for model in parts:
        input_rate, output_rate = lookup_rates(model, prices)
        if input_rate or output_rate:
            return (input_rate, output_rate)
    return lookup_rates(parts[0], prices)


def cost_usd(used_agents, prices: dict) -> float:
    """Return the total USD cost for all agent invocations, rounded to six decimal places."""
    table = enrich_prices(prices)
    total = 0.0
    for agent in used_agents:
        input_rate, output_rate = _rates_for_agent_llm(agent.llm, table)
        total += agent.input_tokens * input_rate / 1_000_000
        total += agent.output_tokens * output_rate / 1_000_000
    return round(total, 6)
