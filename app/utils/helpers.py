from collections.abc import Iterable
from statistics import mean


def safe_mean(values: Iterable[float]) -> float:
    values = list(values)
    return mean(values) if values else 0.0


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
