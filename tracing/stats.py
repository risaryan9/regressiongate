def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile (rounds down). p is 0-1, e.g. 0.95. None if no data."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[int(p * (len(ordered) - 1))]
