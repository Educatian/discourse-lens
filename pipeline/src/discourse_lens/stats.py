"""Statistical inference helpers: bootstrap CI + permutation tests for bias deltas.

All routines are deterministic given a fixed seed (numpy default_rng).
"""
from __future__ import annotations
from typing import Mapping, Sequence

import numpy as np


def _indicator_matrix(
    dois: Sequence[str],
    paper_tags: Mapping[str, list[str]],
    thread_ids: Sequence[str],
) -> np.ndarray:
    """rows=papers, cols=threads, value=1 if paper has thread."""
    K = len(thread_ids)
    X = np.zeros((len(dois), K), dtype=np.int8)
    tid_to_col = {tid: j for j, tid in enumerate(thread_ids)}
    for i, d in enumerate(dois):
        for tid in paper_tags.get(d, []):
            j = tid_to_col.get(tid)
            if j is not None:
                X[i, j] = 1
    return X


def bootstrap_yearly_shares(
    field_papers_by_year: Mapping[int, list[str]],
    paper_tags: Mapping[str, list[str]],
    thread_ids: Sequence[str],
    years: Sequence[int],
    n_boot: int = 1000,
    seed: int = 42,
) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    """Per-year bootstrap percentile 95% CI for thread share within field/year.

    Returns (lo_by_thread, hi_by_thread). Each dict maps thread_id to a
    list of 95% percentile values, one per year (parallel to `years`).
    """
    rng = np.random.default_rng(seed)
    K = len(thread_ids)
    lo = {tid: [0.0] * len(years) for tid in thread_ids}
    hi = {tid: [0.0] * len(years) for tid in thread_ids}

    for yi, yr in enumerate(years):
        dois = field_papers_by_year.get(yr, [])
        n = len(dois)
        if n == 0:
            continue
        X = _indicator_matrix(dois, paper_tags, thread_ids)
        idx = rng.integers(0, n, size=(n_boot, n))
        boots = X[idx].mean(axis=1)   # (n_boot, K)
        lo_arr = np.percentile(boots, 2.5, axis=0)
        hi_arr = np.percentile(boots, 97.5, axis=0)
        for k, tid in enumerate(thread_ids):
            lo[tid][yi] = float(lo_arr[k])
            hi[tid][yi] = float(hi_arr[k])
    return lo, hi


def bias_delta_inference(
    ls_dois: Sequence[str],
    et_dois: Sequence[str],
    paper_tags: Mapping[str, list[str]],
    thread_ids: Sequence[str],
    n_boot: int = 2000,
    n_perm: int = 2000,
    seed: int = 42,
) -> dict[str, dict[str, float]]:
    """For each thread, compute share-bias delta = et_share - ls_share with
    bootstrap percentile CI and a two-sided permutation test p-value
    against the null of identical thread prevalence in both fields.
    """
    rng = np.random.default_rng(seed)
    ls_X = _indicator_matrix(ls_dois, paper_tags, thread_ids)
    et_X = _indicator_matrix(et_dois, paper_tags, thread_ids)
    n_ls, n_et = ls_X.shape[0], et_X.shape[0]
    out: dict[str, dict[str, float]] = {}

    for k, tid in enumerate(thread_ids):
        ls_x = ls_X[:, k]
        et_x = et_X[:, k]
        ls_share = float(ls_x.mean()) if n_ls else 0.0
        et_share = float(et_x.mean()) if n_et else 0.0
        delta = et_share - ls_share

        # Bootstrap delta CI
        ls_idx = rng.integers(0, n_ls, size=(n_boot, n_ls)) if n_ls else None
        et_idx = rng.integers(0, n_et, size=(n_boot, n_et)) if n_et else None
        ls_means = ls_x[ls_idx].mean(axis=1) if ls_idx is not None else np.zeros(n_boot)
        et_means = et_x[et_idx].mean(axis=1) if et_idx is not None else np.zeros(n_boot)
        b_deltas = et_means - ls_means
        delta_lo, delta_hi = np.percentile(b_deltas, [2.5, 97.5])

        # Permutation test: shuffle field labels under H0
        pooled = np.concatenate([ls_x, et_x])
        perm_deltas = np.empty(n_perm, dtype=np.float64)
        for p in range(n_perm):
            rng.shuffle(pooled)
            perm_deltas[p] = pooled[n_ls:].mean() - pooled[:n_ls].mean()
        p_perm = float((np.abs(perm_deltas) >= abs(delta) - 1e-12).mean())

        out[tid] = {
            "ls_share": ls_share,
            "et_share": et_share,
            "delta": delta,
            "delta_lo": float(delta_lo),
            "delta_hi": float(delta_hi),
            "p_perm": p_perm,
            "n_ls": int(n_ls),
            "n_et": int(n_et),
        }
    return out
