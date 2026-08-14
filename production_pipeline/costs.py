"""Cost tracking for Claude API document extraction."""

# Pricing per million tokens by model ID substring (as of May 2026)
_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6":  (3.00,  15.00),
    "claude-sonnet-4-5":  (3.00,  15.00),
    "claude-opus-4-7":    (15.00, 75.00),
    "claude-haiku-4-5":   (0.80,   4.00),
}
_DEFAULT_PRICING = (3.00, 15.00)  # fall back to Sonnet if model unknown


def _get_pricing(model_id: str) -> tuple[float, float]:
    for key, pricing in _PRICING.items():
        if key in model_id:
            return pricing
    return _DEFAULT_PRICING


def compute_real_cost(input_tokens: int, output_tokens: int, model_id: str = "") -> dict:
    """Compute actual cost from real API token usage.

    Returns:
        {input_tokens, output_tokens, input_cost, output_cost, total_cost, model_id}
    """
    input_rate, output_rate = _get_pricing(model_id)
    input_cost  = (input_tokens  / 1_000_000) * input_rate
    output_cost = (output_tokens / 1_000_000) * output_rate

    return {
        "input_tokens":  input_tokens,
        "output_tokens": output_tokens,
        "input_cost":    input_cost,
        "output_cost":   output_cost,
        "total_cost":    input_cost + output_cost,
        "model_id":      model_id,
    }


def format_cost(cost: float) -> str:
    return f"${cost:.3f}"
