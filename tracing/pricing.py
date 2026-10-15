"""USD prices per million tokens, as (input, output)."""

PRICES: dict[str, tuple[float, float]] = {
    # Haiku 5.5 doubles past 100K-token prompts; our tickets never get close.
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}


def cost_usd(model: str, tokens_in: int, tokens_out: int) -> float | None:
    """Cost of one call, or None for a model we have no price for."""
    price = PRICES.get(model)
    if price is None:
        return None
    return (tokens_in * price[0] + tokens_out * price[1]) / 1_000_000
