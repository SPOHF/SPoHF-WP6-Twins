"""Pure frame-in/frame-out feature construction for red's climate model.

No I/O, so the part most worth getting right — what each row is allowed to know
— is testable without a database.

Two rules hold everything together:

**Hours, not rows.** Every series is reindexed onto a complete hourly grid
before anything is shifted. Red's sensors drop out for hours at a time, so
``shift(3)`` on the raw rows would mean "three readings ago", which during a gap
can be most of a day. Reindexing first makes a lag a real duration, and turns a
gap into NaN that the final dropna removes.

**Nothing may know its own future.** Autoregressive columns are read at ``t``;
exogenous (weather) columns are read at ``t + horizon``, which is legitimate
because a forecast supplies them. The indoor value at ``t + horizon`` appears
only as the target. Anything else would be a leak that no held-out split can
detect, because the leak is inside the row.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from wp6_data.shared.aggregation import HOURLY, HOURS_PER_DAY, resample_hourly

# Suffix for a lagged column; lag 0 keeps the bare column name.
LAG_SUFFIX = "_lag{hours}h"


@dataclass(frozen=True)
class SupervisedSet:
    """One horizon's training matrix, plus what a fair comparison needs.

    ``y_now`` is the target's value at ``t`` — carried alongside precisely so
    the persistence baseline can be computed on exactly the rows the model was
    scored on, rather than reconstructed later and misaligned.
    """

    X: np.ndarray
    y: np.ndarray
    feature_names: list[str]
    time_at: pd.Series
    time_target: pd.Series
    y_now: np.ndarray
    days: np.ndarray = field(default_factory=lambda: np.array([]))

    def __len__(self) -> int:
        return len(self.y)


def hourly_frame(series: dict[str, pd.DataFrame], *, time_col: str = "time",
                 value_col: str = "value") -> pd.DataFrame:
    """Join named hourly series into one frame on a complete hourly index.

    The index spans the union of all inputs with no hour missing, so a later
    shift is a duration. Where a series has no reading the cell is NaN, which is
    what makes a gap propagate honestly into every window that touches it.
    """
    frames = {
        name: resample_hourly(df, time_col=time_col, value_col=value_col)
        .set_index(time_col)[value_col]
        .rename(name)
        for name, df in series.items()
        if not df.empty
    }
    if not frames:
        return pd.DataFrame()

    joined = pd.concat(frames.values(), axis=1)
    full = pd.date_range(joined.index.min(), joined.index.max(), freq=HOURLY, tz="UTC")
    return joined.reindex(full).rename_axis(time_col)


def lag_columns(
    frame: pd.DataFrame, columns: Sequence[str], lags: Sequence[int]
) -> tuple[pd.DataFrame, list[str]]:
    """Past values of ``columns`` at each lag in hours, including lag 0.

    Lag 0 — the value right now — is included deliberately: it is the single
    most informative feature at short horizons, and it is also exactly what the
    persistence baseline uses, so including it is what forces the model to earn
    its skill rather than inherit it.
    """
    built: dict[str, pd.Series] = {}
    names: list[str] = []
    for column in columns:
        if column not in frame:
            continue
        for lag in [0, *lags]:
            name = column if lag == 0 else column + LAG_SUFFIX.format(hours=lag)
            built[name] = frame[column].shift(lag)
            names.append(name)
    return pd.DataFrame(built, index=frame.index), names


def seasonal_columns(index: pd.DatetimeIndex, *, with_day_of_year: bool) -> pd.DataFrame:
    """Cyclical time encodings for ``index``.

    ``with_day_of_year`` is a real choice, not a default. A model fitted on a
    single season has no basis for a day-of-year coefficient: it would fit the
    trend *within* that season and extrapolate it confidently into months it has
    never seen. Link 3 therefore asks for hour-of-day only.
    """
    hour_angle = 2 * np.pi * index.hour / HOURS_PER_DAY
    built = {
        "hour_of_day_sin": np.sin(hour_angle),
        "hour_of_day_cos": np.cos(hour_angle),
    }
    if with_day_of_year:
        day_angle = 2 * np.pi * index.dayofyear / 365
        built["day_of_year_sin"] = np.sin(day_angle)
        built["day_of_year_cos"] = np.cos(day_angle)
    return pd.DataFrame(built, index=index)


def feature_frame(
    frame: pd.DataFrame,
    *,
    horizon_hours: int,
    lag_hours: Sequence[int],
    autoregressive: Sequence[str] = (),
    exogenous: Sequence[str] = (),
    with_day_of_year: bool = True,
) -> tuple[pd.DataFrame, list[str]]:
    """The feature columns for one horizon, indexed by the time of prediction.

    Shared by training and prediction so the two cannot drift: a feature built
    one way when fitting and another way when serving is a mismatch no test of
    either path alone would catch.
    """
    index = frame.index
    lagged, lag_names = lag_columns(frame, autoregressive, lag_hours)
    ahead = pd.DataFrame(
        {name: frame[name].shift(-horizon_hours) for name in exogenous if name in frame},
        index=index,
    )
    seasonal = seasonal_columns(
        index + pd.Timedelta(hours=horizon_hours), with_day_of_year=with_day_of_year
    ).set_axis(index)

    features = pd.concat([lagged, ahead, seasonal], axis=1)
    return features, [*lag_names, *ahead.columns, *seasonal.columns]


def feature_row(
    frame: pd.DataFrame,
    *,
    at: pd.Timestamp,
    horizon_hours: int,
    lag_hours: Sequence[int],
    autoregressive: Sequence[str] = (),
    exogenous: Sequence[str] = (),
    with_day_of_year: bool = True,
) -> tuple[np.ndarray, list[str]] | None:
    """One row of features for predicting ``at + horizon_hours``.

    Returns ``None`` when any input for that row is missing — a prediction with
    a silently defaulted lag would be worse than no prediction, because nothing
    downstream could tell the difference.

    The frame must already carry the exogenous columns *into the future*, since
    they are read at ``at + horizon_hours``; the caller supplies those from a
    weather forecast run through link 1.
    """
    features, names = feature_frame(
        frame,
        horizon_hours=horizon_hours,
        lag_hours=lag_hours,
        autoregressive=autoregressive,
        exogenous=exogenous,
        with_day_of_year=with_day_of_year,
    )
    if at not in features.index:
        return None
    row = features.loc[at, names]
    if row.isna().any():
        return None
    return row.to_numpy(dtype=float).reshape(1, -1), names


def build_supervised(
    frame: pd.DataFrame,
    target: str,
    *,
    horizon_hours: int,
    lag_hours: Sequence[int],
    autoregressive: Sequence[str] = (),
    exogenous: Sequence[str] = (),
    with_day_of_year: bool = True,
) -> SupervisedSet:
    """Assemble one horizon's supervised problem from an hourly frame.

    Each row predicts ``target`` at ``t + horizon_hours`` from:

    - ``autoregressive`` columns at ``t`` and at each lag (the greenhouse's
      recent state),
    - ``exogenous`` columns at ``t + horizon_hours`` (weather, which a forecast
      supplies),
    - cyclical time encodings of ``t + horizon_hours``.

    Rows with any missing input or target are dropped, so an excluded or absent
    stretch removes every window that reaches into it rather than being quietly
    interpolated across.
    """
    if frame.empty or target not in frame:
        return SupervisedSet(
            X=np.empty((0, 0)), y=np.array([]), feature_names=[],
            time_at=pd.Series(dtype="datetime64[ns, UTC]"),
            time_target=pd.Series(dtype="datetime64[ns, UTC]"),
            y_now=np.array([]), days=np.array([]),
        )

    features, feature_names = feature_frame(
        frame,
        horizon_hours=horizon_hours,
        lag_hours=lag_hours,
        autoregressive=autoregressive,
        exogenous=exogenous,
        with_day_of_year=with_day_of_year,
    )
    y = frame[target].shift(-horizon_hours)
    y_now = frame[target]

    assembled = features.assign(_y=y, _y_now=y_now).dropna()

    at = pd.Series(assembled.index, name="time_at")
    return SupervisedSet(
        X=assembled[feature_names].to_numpy(dtype=float),
        y=assembled["_y"].to_numpy(dtype=float),
        feature_names=feature_names,
        time_at=at,
        time_target=at + pd.Timedelta(hours=horizon_hours),
        y_now=assembled["_y_now"].to_numpy(dtype=float),
        days=np.array([ts.date() for ts in assembled.index]),
    )
