"""The gate's statistics (design VAL-6, §11.8): a one-sided 95% BCa bootstrap over role keys, the p-value
of "the difference is at least d", and the Holm step-down at 0.05.

The unit resampled is the role key, not the unit: a key's units have correlated errors, and all of a
key's units travel together. The input is one number per role key, the key's mean paired difference
(candidate error minus base error). The resamples come from a named substream, so the same pre-registration
gives the same p-values (INV-6).
"""
from __future__ import annotations

import hashlib
from statistics import NormalDist

import numpy as np

B = 10_000
ALPHA = 0.05
P_FLOOR = 1e-4
_N = NormalDist()


def rng_for(substream: str, *labels: str) -> np.random.Generator:
    """A generator named by the pre-registration's substream and the lane, criterion and metric it serves."""
    h = hashlib.sha256("\0".join((substream, *labels)).encode("utf-8")).digest()
    return np.random.default_rng(np.random.SeedSequence(int.from_bytes(h[:16], "big")))


def bootstrap(d: np.ndarray, rng: np.random.Generator, b: int = B) -> np.ndarray:
    k, out, step = len(d), np.empty(b), 500
    for lo in range(0, b, step):
        n = min(step, b - lo)
        out[lo:lo + n] = d[rng.integers(0, k, size=(n, k))].mean(axis=1)
    return out


def _acceleration(d: np.ndarray) -> float:
    k = len(d)
    jack = (d.sum() - d) / (k - 1)
    dev = jack.mean() - jack
    den = 6.0 * (dev ** 2).sum() ** 1.5
    return float((dev ** 3).sum() / den) if den > 0 else 0.0


def bca_upper(boot: np.ndarray, theta: float, a: float, alpha: float) -> float:
    """The upper end of the one-sided BCa interval at level 1 - alpha."""
    b = len(boot)
    below = (np.count_nonzero(boot < theta) + 0.5 * np.count_nonzero(boot == theta)) / b
    z0 = _N.inv_cdf(min(max(below, 0.5 / b), 1 - 0.5 / b))
    z = _N.inv_cdf(1 - alpha)
    den = 1 - a * (z0 + z)
    adj = 1.0 if den <= 0 else _N.cdf(z0 + (z0 + z) / den)
    return float(np.quantile(boot, min(max(adj, 0.0), 1.0)))


def analyse(d: np.ndarray, null: float, rng: np.random.Generator, b: int = B) -> dict:
    """The difference's mean, the upper end of its one-sided 95% BCa interval, and the p-value of the null
    "the difference is at least `null`": the smallest one-sided level at which the BCa upper end falls below
    `null`. `below_floor` is true when p is under 1e-4, and p is then the floor."""
    d = np.asarray(d, dtype=float)
    if len(d) < 2:
        raise ValueError("a bootstrap over fewer than two role keys")
    theta = float(d.mean())
    if np.ptp(d) == 0.0:
        p, below = (P_FLOOR, True) if theta < null else (1.0, False)
        return {"difference": theta, "upper_95": theta, "p": p, "below_floor": below}
    boot = bootstrap(d, rng, b)
    a = _acceleration(d)
    upper = bca_upper(boot, theta, a, ALPHA)
    if bca_upper(boot, theta, a, P_FLOOR) < null:
        p, below = P_FLOOR, True
    elif bca_upper(boot, theta, a, 1 - P_FLOOR) >= null:
        p, below = 1.0, False
    else:
        p, below = _bisect(boot, theta, a, null), False
    return {"difference": theta, "upper_95": upper, "p": p, "below_floor": below}


def _bisect(boot, theta, a, null):
    lo, hi = P_FLOOR, 1 - P_FLOOR          # upper(lo) >= null > upper(hi)
    for _ in range(60):
        mid = (lo + hi) / 2
        if bca_upper(boot, theta, a, mid) < null:
            hi = mid
        else:
            lo = mid
    return hi


def holm(ps: list[float], alpha: float = ALPHA) -> list[bool]:
    """Holm step-down: which hypotheses are rejected, in the order of `ps`."""
    m, order, rejected = len(ps), sorted(range(len(ps)), key=lambda i: ps[i]), [False] * len(ps)
    for rank, i in enumerate(order):
        if ps[i] > alpha / (m - rank):
            break
        rejected[i] = True
    return rejected
