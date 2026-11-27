"""Small helpers the pure parts share. Pure Python."""
from __future__ import annotations

import math
from typing import Any, TypeVar

T = TypeVar("T")


def num(value: Any) -> float | None:
    """A finite number from a state, an attribute or a stored value; None for text, NaN and infinity."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def fill(obj: T, d: dict | None) -> T:
    """Stored values back into a fresh object: only fields it has (stored data from another version may have more,
    or fewer), never a computed property."""
    for k, v in (d or {}).items():
        if hasattr(obj, k) and not isinstance(getattr(type(obj), k, None), property):
            setattr(obj, k, v)
    return obj


def solve(A: list[list[float]], b: list[float]) -> list[float] | None:
    """A x = b by Gauss-Jordan with partial pivoting; None when A is (nearly) singular."""
    n = len(b)
    M = [A[i][:] + [b[i]] for i in range(n)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-12:
            return None
        M[c], M[p] = M[p], M[c]
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] for i in range(n)]
