"""Shared fitting and scoring for red's models.

Twin-local. Every red model that fits a regularised linear stage comes through
here, so the recipe — standardise, RidgeCV, report — is written once rather than
copied per model.

The scoring half is the point of the module. A model of a slowly-moving indoor
quantity can post a spectacular R² while being worthless, because "whatever it
is now" is already an excellent prediction an hour out. So a score is only
reported here alongside the **baselines it has to beat**:

- :func:`persistence_baseline` — carry the value at ``t`` forward.
- :func:`climatology_baseline` — the mean for this hour-of-day and month.
- :func:`reference_baseline` — for a per-height model, assume the height simply
  equals its greenhouse-level reference. If modelling the gradient does not beat
  ignoring the gradient, the model has earned nothing.

:func:`time_blocked_splits` exists for the same reason. Neighbouring hours are
near-duplicates, so a random fold trains on the test set's twins and every score
comes back flattering. Folds here are contiguous blocks of whole days.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

# Regularisation strengths RidgeCV picks between. Wide and log-spaced: the
# stages differ by orders of magnitude in feature scale and sample count.
DEFAULT_ALPHAS: tuple[float, ...] = (0.01, 0.1, 1.0, 10.0, 100.0, 1000.0)

# Folds for cross-validated alpha selection.
DEFAULT_CV_FOLDS = 5


@dataclass
class StageStats:
    """Fit quality for a single model stage.

    ``r2_score``/``rmse``/``mae`` are in-sample. The ``holdout_*`` fields carry
    the same measures on data the fit never saw, and are the ones worth reading;
    they stay ``None`` for a caller that did not pass a held-out set, so an
    absent out-of-sample score is visibly absent rather than silently equal to
    the in-sample one.
    """

    r2_score: float
    rmse: float
    mae: float
    n_samples: int
    coefficients: dict[str, float]
    intercept: float
    feature_names: list[str] = field(default_factory=list)
    holdout_r2: float | None = None
    holdout_rmse: float | None = None
    holdout_mae: float | None = None
    n_holdout: int = 0
    # baseline name -> skill score on the held-out set; see `skill_score`.
    skill: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class GradientScore:
    """How well a per-height prediction reproduces the vertical profile.

    A model can be right about every height's mean and still draw the profile
    upside down, which is the part a grower actually reads. So the profile is
    scored separately, relative to a base height.
    """

    rmse: float
    sign_agreement: float
    n: int


def rmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Root mean squared error, in the units of ``actual``."""
    return float(np.sqrt(np.mean((np.asarray(actual) - np.asarray(predicted)) ** 2)))


def mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Mean absolute error, in the units of ``actual``."""
    return float(np.mean(np.abs(np.asarray(actual) - np.asarray(predicted))))


def skill_score(model_error: float, baseline_error: float) -> float:
    """Fraction of the baseline's error the model removes.

    ``1.0`` is perfect, ``0.0`` is no better than the baseline, and **negative
    means worse than the baseline** — which is a real and reportable outcome,
    not a bug. Returns 0.0 when the baseline is already perfect, since there is
    no error left to improve on.
    """
    if baseline_error == 0:
        return 0.0
    return float(1.0 - (model_error / baseline_error))


def time_blocked_splits(
    days: Sequence[Any], n_splits: int = DEFAULT_CV_FOLDS
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Cross-validation folds that never split a calendar day.

    ``days`` is the day each row belongs to, in row order. Unique days are cut
    into ``n_splits`` **contiguous** blocks; each block is held out in turn.

    Contiguous rather than scattered on purpose: hourly rows an hour apart are
    near-identical, so scattering days across folds leaks almost as badly as
    scattering rows. A held-out block is a stretch of time the fit genuinely did
    not see.

    Yields ``(train_idx, test_idx)`` index arrays. A fold whose training side
    would be empty is skipped, so fewer than ``n_splits`` folds may be yielded.
    """
    day_array = np.asarray(days)
    unique = np.unique(day_array)
    if n_splits < 2 or len(unique) < 2:
        return
    for block in np.array_split(unique, min(n_splits, len(unique))):
        if len(block) == 0:
            continue
        mask = np.isin(day_array, block)
        train_idx = np.flatnonzero(~mask)
        test_idx = np.flatnonzero(mask)
        if len(train_idx) == 0 or len(test_idx) == 0:
            continue
        yield train_idx, test_idx


def fit_ridge(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    *,
    days: Sequence[Any] | None = None,
    alphas: Sequence[float] = DEFAULT_ALPHAS,
    cv: int = DEFAULT_CV_FOLDS,
) -> tuple[Any, Any, StageStats]:
    """Standardise, fit a cross-validated ridge, and report in-sample quality.

    Pass ``days`` to select alpha on day-blocked folds
    (:func:`time_blocked_splits`) instead of scikit-learn's random K-fold. Any
    model with lagged features must pass it; without it, adjacent near-duplicate
    rows land on both sides of a fold and the chosen alpha is tuned against a
    leak.

    Returns ``(model, scaler, stats)``. Held-out measures are the caller's job —
    it owns the split — and go on the returned stats via :func:`score_holdout`.
    """
    from sklearn.linear_model import RidgeCV
    from sklearn.metrics import r2_score
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    folds: Any = cv
    if days is not None:
        blocked = list(time_blocked_splits(days, cv))
        if blocked:
            folds = blocked

    model = RidgeCV(alphas=list(alphas), cv=folds)
    model.fit(X_scaled, y)
    predicted = model.predict(X_scaled)

    return (
        model,
        scaler,
        StageStats(
            r2_score=round(float(r2_score(y, predicted)), 4),
            rmse=round(rmse(y, predicted), 3),
            mae=round(mae(y, predicted), 3),
            n_samples=int(len(y)),
            coefficients=dict(zip(feature_names, model.coef_, strict=True)),
            intercept=round(float(model.intercept_), 4),
            feature_names=list(feature_names),
        ),
    )


def out_of_fold_predictions(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    days: Sequence[Any],
    *,
    n_splits: int = DEFAULT_CV_FOLDS,
    alphas: Sequence[float] = DEFAULT_ALPHAS,
) -> tuple[np.ndarray, np.ndarray]:
    """Predict every row from a fit that never saw the block it belongs to.

    Each day-block is held out in turn and predicted by a model fitted on the
    rest, so the returned predictions are out-of-sample for every row while
    still covering the whole span. That matters here: a single trailing holdout
    would test one season, and a model fitted mostly on winter would be scored
    only on summer (or the reverse) without the score ever saying so.

    Returns ``(predictions, mask)`` where ``mask`` marks the rows that belonged
    to some held-out block and therefore carry a real out-of-fold prediction.
    """
    predictions = np.full(len(y), np.nan, dtype=float)
    folds = list(time_blocked_splits(days, n_splits))
    for train_idx, test_idx in folds:
        model, scaler, _ = fit_ridge(
            X[train_idx], y[train_idx], feature_names,
            days=np.asarray(days)[train_idx], alphas=alphas,
        )
        predictions[test_idx] = model.predict(scaler.transform(X[test_idx]))
    return predictions, ~np.isnan(predictions)


def score_holdout(
    stats: StageStats,
    actual: np.ndarray,
    predicted: np.ndarray,
    baselines: dict[str, np.ndarray] | None = None,
) -> StageStats:
    """Attach held-out measures, and skill against each baseline, to ``stats``.

    Mutates and returns ``stats`` so a fit and its out-of-sample verdict stay
    one object. ``baselines`` maps a name to that baseline's predictions over
    the same held-out rows.
    """
    from sklearn.metrics import r2_score

    actual = np.asarray(actual)
    predicted = np.asarray(predicted)
    stats.holdout_r2 = round(float(r2_score(actual, predicted)), 4)
    stats.holdout_rmse = round(rmse(actual, predicted), 3)
    stats.holdout_mae = round(mae(actual, predicted), 3)
    stats.n_holdout = int(len(actual))

    model_error = rmse(actual, predicted)
    for name, baseline in (baselines or {}).items():
        stats.skill[name] = round(skill_score(model_error, rmse(actual, baseline)), 4)
    return stats


def persistence_baseline(value_now: Sequence[float]) -> np.ndarray:
    """Carry the value at ``t`` forward to ``t+h`` unchanged.

    The hardest baseline to beat at short horizons, and the reason a raw R² on
    an hourly indoor series means very little on its own.
    """
    return np.asarray(value_now, dtype=float)


def climatology_table(
    times: pd.Series, values: Sequence[float]
) -> dict[tuple[int, int], float]:
    """Mean value per ``(month, hour)``, built from training rows only.

    Kept separate from :func:`climatology_baseline` precisely so the table can
    be built on the training side of a split and applied to the held-out side.
    Building it over everything would leak the test period into its own baseline
    and understate the model's skill.
    """
    frame = pd.DataFrame({"time": pd.to_datetime(times, utc=True), "value": list(values)})
    keys = list(zip(frame["time"].dt.month, frame["time"].dt.hour, strict=True))
    frame["key"] = keys
    return {key: float(mean) for key, mean in frame.groupby("key")["value"].mean().items()}


def climatology_baseline(
    table: dict[tuple[int, int], float], times: pd.Series, fallback: float
) -> np.ndarray:
    """Apply a :func:`climatology_table` to ``times``.

    ``fallback`` covers a ``(month, hour)`` the training side never saw — which
    is exactly what happens when a model trained on one season is asked about
    another, so it must not silently become zero.
    """
    stamps = pd.to_datetime(times, utc=True)
    return np.array(
        [
            table.get((int(t.month), int(t.hour)), fallback)
            for t in stamps
        ],
        dtype=float,
    )


def reference_baseline(reference_values: Sequence[float]) -> np.ndarray:
    """Assume a height simply equals its greenhouse-level reference.

    The baseline that decides whether a per-height model is worth having: it is
    what you get by ignoring the vertical gradient entirely.
    """
    return np.asarray(reference_values, dtype=float)


def gradient_error(
    predicted: pd.DataFrame, actual: pd.DataFrame, *, base_height: int
) -> GradientScore:
    """Score the vertical profile shape, not each height's level.

    Both frames are wide — one row per timestamp, one column per height. Each is
    re-expressed as a difference from ``base_height``, so a model that is
    uniformly two degrees warm scores perfectly here while one that inverts the
    profile scores badly. ``sign_agreement`` is the share of comparisons where
    the gradient points the same way in both.

    Columns absent from either frame, and rows where either side is missing, are
    dropped rather than filled — an unobserved height must not read as zero
    gradient.
    """
    heights = [h for h in predicted.columns if h in actual.columns and h != base_height]
    if base_height not in predicted.columns or base_height not in actual.columns:
        return GradientScore(rmse=float("nan"), sign_agreement=float("nan"), n=0)

    pred_profile = predicted[heights].sub(predicted[base_height], axis=0)
    true_profile = actual[heights].sub(actual[base_height], axis=0)

    pred_flat = pred_profile.to_numpy(dtype=float).ravel()
    true_flat = true_profile.to_numpy(dtype=float).ravel()
    keep = ~(np.isnan(pred_flat) | np.isnan(true_flat))
    pred_flat, true_flat = pred_flat[keep], true_flat[keep]

    if len(pred_flat) == 0:
        return GradientScore(rmse=float("nan"), sign_agreement=float("nan"), n=0)

    agree = float(np.mean(np.sign(pred_flat) == np.sign(true_flat)))
    return GradientScore(
        rmse=round(rmse(true_flat, pred_flat), 3),
        sign_agreement=round(agree, 4),
        n=int(len(pred_flat)),
    )
