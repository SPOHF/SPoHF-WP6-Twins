"""One day of the greenhouse as the /greenhouse page draws it.

:func:`build_day` is pure — a 5-minute LetsGrow frame in, a JSON-ready dict
out — so everything the page shows can be tested without a database;
:func:`fetch_five_minute` is the one place that reads the store.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from wp6_data.red.greenhouse import advice as A
from wp6_data.red.greenhouse import physics as P
from wp6_data.red.greenhouse import state as S
from wp6_data.red.greenhouse import sun
from wp6_data.red.greenhouse import transpiration as T
from wp6_data.red.greenhouse.config import GreenhouseConfig
from wp6_data.red.greenhouse.explain import pipe_label
from wp6_data.shared.i18n import t

STATE_FIELDS = (
    "t_in",
    "rh_in",
    "ah_in",
    "t_out",
    "rh_out",
    "ah_out",
    "wind",
    "wind_dir",
    "radiation",
    "lamps",
    "vent_lee",
    "vent_wind",
    "vent",
    "screen",
    "co2",
    "heat_sp",
    "lg_pipe_lower",
    "lg_pipe_growth",
    "lg_pipe_lower_calc",
    "lg_pipe_growth_calc",
    "weight",
    "ec_drain",
    "transpiration",
)
FLOW_FIELDS = (
    "sun",
    "lamps",
    "pipes",
    "cover",
    "ventilation",
    "evaporation",
    "residual",
    "air_exchange",
    "vapour_out",
)


async def fetch_five_minute(day: date, cfg: GreenhouseConfig, tz: str) -> pd.DataFrame:
    """LetsGrow for ``day`` and its margins, as the 5-minute frame."""
    from wp6_data.red.tsdb import fetch_data_tsdb

    start, end = S.window(day, tz)
    tags = sorted({tag for (_, tag) in S.COLUMNS})
    d = cfg.devices
    long = await fetch_data_tsdb(
        sensor_tags=tags,
        device_names=[d.climate, d.lamps, d.water, d.weather],
        start=start.to_pydatetime(),
        end=end.to_pydatetime(),
        limit=200_000,
    )
    return S.five_minute(long, cfg, tz)


def _num(x) -> float | None:
    if x is None:
        return None
    x = float(x)
    return round(x, 3) if np.isfinite(x) else None


def _activity(f5: pd.DataFrame, s: pd.DataFrame, cfg: GreenhouseConfig, day: date) -> dict:
    """When the crop woke, from the scale: after lamps-on in the dark, or sunrise."""
    measured = T.quiet_rate(f5["weight"], f5["irrigation"], cfg)
    tz = f5.index.tz
    start = pd.Timestamp(day, tz=tz)
    lamps = (f5["lamp_on"].clip(0, 1) * f5["lamp_pct"].clip(0, 100) / 100).fillna(0)
    on = (lamps > 0.5) & (f5["radiation"].fillna(0) <= 0)
    switch = (
        on
        & ~on.shift(1, fill_value=False)
        & (f5.index >= start - pd.Timedelta(hours=2))
        & (f5.index < start + pd.Timedelta(hours=12))
    )
    sunrise = (
        (f5["radiation"].fillna(0) > 0)
        & (f5.index >= start)
        & (f5.index < start + pd.Timedelta(hours=12))
    )
    trigger, cause = None, None
    if switch.any():
        trigger, cause = switch[switch].index[0], "lamps"
    elif sunrise.any():
        trigger, cause = sunrise[sunrise].index[0], "sunrise"
    woke = T.wake_time(measured, trigger) if trigger is not None else None
    wake = woke["time"] if woke else None
    return {
        "dark_rate_ml": _num(woke["before"] * 1000) if woke else None,
        "plateau_ml": _num(woke["plateau"] * 1000) if woke else None,
        "trigger": trigger.strftime("%H:%M") if trigger is not None else None,
        "cause": cause,
        "wake": wake.strftime("%H:%M") if wake is not None else None,
        "lag_min": round((wake - trigger).total_seconds() / 60) if wake is not None else None,
        "_wake_ts": wake,
    }


def build_day(
    f5: pd.DataFrame,
    day: date,
    cfg: GreenhouseConfig,
    tz: str,
    latitude: float,
    longitude: float,
) -> dict:
    """Everything the page draws for ``day``."""
    s = S.day_frame(f5, day, cfg, tz)
    if s["t_in"].notna().sum() < 48:
        return {
            "date": day.isoformat(),
            "tz": tz,
            "empty": True,
            "notes": [t("greenhouse.note.short_day")],
        }
    model_in = s.assign(transpiration=s["transpiration"].fillna(0))
    flows = P.balance(model_in, cfg)
    screen_closed = (
        P.what_if(model_in, cfg, screen=1.0) if s["screen_logged"].astype(bool).any() else None
    )
    light = A.light_period(f5, pd.Timestamp(day, tz=tz))
    advice, plan = A.advise(s, flows, cfg, screen_closed, light)
    act = _activity(f5, s, cfg, day)
    irr = A.irrigation_timing(s, f5, act.pop("_wake_ts"))
    if irr is not None:
        advice.append(irr)
    pos = sun.position(s.index, latitude, longitude)
    water = S.water_balance(f5, day, cfg)

    steps = []
    for i, when in enumerate(s.index):
        row = s.iloc[i]
        st = {k: _num(row.get(k)) for k in STATE_FIELDS}
        if not bool(row.get("screen_logged")):
            st["screen"] = None
        fl = {k: _num(flows[k].iloc[i]) for k in FLOW_FIELDS}
        for p in cfg.pipes:
            fl[f"pipe:{p.tag}"] = _num(flows[f"pipe:{p.tag}"].iloc[i])
        steps.append(
            {
                "t": when.strftime("%H:%M"),
                "sun_el": _num(pos["elevation"].iloc[i]),
                "sun_az": _num(pos["azimuth"].iloc[i]),
                "state": st,
                "flows": fl,
                "e_source": row["transpiration_source"],
            }
        )

    mj = lambda col: _num(flows[col].fillna(0).sum() * 0.25 * 3600 / 1e6)  # noqa: E731
    summary = {
        "heat_mj": mj("pipes") or 0.0,
        "lamp_h": _num(s["lamps"].fillna(0).sum() * 0.25),
        "lamp_h_needed": _num(plan["lamp_h_needed"]) if plan else None,
        "lamp_h_longest_day": _num(plan["lamp_h_longest_day"]) if plan else None,
        **light,
        **sun.rise_and_set(pd.Timestamp(day, tz=tz), latitude, longitude),
        "sun_jcm2": _num(s["radiation"].fillna(0).sum() * 0.25 * 3600 / 1e4),
        "light_jcm2": _num(
            s["radiation"].fillna(0).sum() * 0.25 * 3600 / 1e4
            + s["lamps"].fillna(0).sum() * 0.25 * cfg.lamps.radiation_eq
        ),
        "transpiration_l": _num(
            water["transpiration"]
            if water["transpiration"] is not None
            else s["transpiration"].sum() * 0.25
        ),
        "irrigation_l": _num(water["irrigation"]),
        "drain_l": _num(water["drain"]),
        "humid_h": _num((s["rh_in"] >= cfg.advice.humid_rh).sum() * 0.25),
        "t_mean": _num(s["t_in"].mean()),
        "t_min": _num(s["t_in"].min()),
        "t_out_mean": _num(s["t_out"].mean()),
        "flows_mj": {
            k: mj(k)
            for k in ("sun", "lamps", "pipes", "cover", "ventilation", "evaporation", "residual")
        },
        "scale_share": _num((s["transpiration_source"] == "scale").mean()),
    }
    notes = []
    if not s["screen_logged"].astype(bool).any():
        notes.append(t("greenhouse.note.no_curtain"))
    return {
        "date": day.isoformat(),
        "tz": tz,
        "site": {"lat": latitude, "lon": longitude},
        "steps": steps,
        "summary": summary,
        "advice": [a.as_dict() for a in advice],
        "light": plan,
        "activity": act,
        "notes": notes,
        "params": _params(cfg),
    }


def _params(cfg: GreenhouseConfig) -> dict:
    """The configured values the page draws with, whether LetsGrow delivered or not."""
    return {
        "lamp_w": cfg.lamps.power_w,
        "lamp_jcm2_per_h": cfg.lamps.radiation_eq,
        "pipes": [{"tag": p.tag, "label": pipe_label(p.tag, p.label)} for p in cfg.pipes],
        "advice": cfg.advice.model_dump(),
    }


#: What a day's summary carries (see :func:`build_day`), for days that have none.
SUMMARY_FIELDS = (
    "heat_mj", "lamp_h", "lamp_h_needed", "lamp_h_longest_day", "sun_jcm2", "light_jcm2",
    "transpiration_l", "irrigation_l", "drain_l", "humid_h", "t_mean", "t_min", "t_out_mean",
    "scale_share", "light_h", "sun_h", "lamp_only_h", "dark_h", "longest_dark_h", "longest_dark",
)


def bare_day(
    day: date, cfg: GreenhouseConfig, tz: str, latitude: float, longitude: float
) -> dict:
    """A day LetsGrow has not delivered: the page's day with only the sun in it.

    The multi-height sensors run ahead of LetsGrow, so their microclimate can be
    shown for days the climate computer has not sent yet. This is the frame for
    those days: every step, where the sun stands, sunrise and sunset, and every
    LetsGrow value empty (``None``) rather than guessed. ``letsgrow`` is false so
    the page can say so.
    """
    start = pd.Timestamp(day, tz=tz)
    index = pd.date_range(start, start + pd.Timedelta(days=1), freq=S.STEP, inclusive="left")
    pos = sun.position(index, latitude, longitude)
    flows_mj = ("sun", "lamps", "pipes", "cover", "ventilation", "evaporation", "residual")
    return {
        "date": day.isoformat(),
        "tz": tz,
        "site": {"lat": latitude, "lon": longitude},
        "letsgrow": False,
        "steps": [
            {
                "t": when.strftime("%H:%M"),
                "sun_el": _num(pos["elevation"].iloc[i]),
                "sun_az": _num(pos["azimuth"].iloc[i]),
                "state": dict.fromkeys(STATE_FIELDS),
                "flows": dict.fromkeys(FLOW_FIELDS),
                "e_source": None,
            }
            for i, when in enumerate(index)
        ],
        "summary": {
            **dict.fromkeys(SUMMARY_FIELDS),
            **sun.rise_and_set(start, latitude, longitude),
            "flows_mj": dict.fromkeys(flows_mj),
        },
        "advice": [],
        "light": None,
        "activity": {},
        "notes": [t("greenhouse.note.not_delivered")],
        "params": _params(cfg),
    }


def what_if_day(
    f5: pd.DataFrame,
    day: date,
    cfg: GreenhouseConfig,
    tz: str,
    *,
    vent_scale: float | None = None,
    screen_dark: float | None = None,
    lamps: str | None = None,
) -> dict:
    """The day under other settings, summarised against what ran.

    ``vent_scale`` multiplies every vent opening; ``screen_dark`` (0-1) sets the
    screen in hours without sun; ``lamps="off"`` takes the lamps out.
    """
    s = S.day_frame(f5, day, cfg, tz).assign(transpiration=lambda x: x["transpiration"].fillna(0))
    settings: dict[str, pd.Series | float] = {}
    if vent_scale is not None:
        settings["vent"] = (s["vent"].fillna(0) * vent_scale).clip(0, 1)
    if screen_dark is not None:
        settings["screen"] = s["screen"].fillna(0).where(s["radiation"] > 5, screen_dark)
    if lamps == "off":
        settings["lamps"] = 0.0
    elif lamps is not None:
        raise ValueError(f"unknown lamp setting {lamps!r}")
    w = P.what_if(s, cfg, **settings)
    base = P.balance(s, cfg)
    to_mj = 0.25 * 3600 / 1e6
    heat_base = float(base["pipes"].fillna(0).sum() * to_mj)
    heat_alt = float(w["pipes"].fillna(0).sum() * to_mj)
    humid = cfg.advice.humid_rh
    return {
        "heat_mj": round(heat_base, 3),
        "heat_mj_whatif": round(heat_alt, 3),
        "surplus_mj": round(float(w["surplus"].sum() * to_mj), 3),
        "humid_h": round(float((s["rh_in"] >= humid).sum() * 0.25), 2),
        "humid_h_whatif": round(float((w["rh"] >= humid).sum() * 0.25), 2),
        "rh_max_whatif": round(float(w["rh"].max()), 1),
        "series": {
            "t": [x.strftime("%H:%M") for x in s.index],
            "pipes": [_num(x) for x in base["pipes"]],
            "pipes_whatif": [_num(x) for x in w["pipes"]],
            "rh": [_num(x) for x in s["rh_in"]],
            "rh_whatif": [_num(x) for x in w["rh"]],
        },
    }


def latest_day(now: datetime, last_reading: pd.Timestamp | None, tz: str) -> date:
    """The newest local day LetsGrow has delivered in full (it runs ~2 days late)."""
    if last_reading is None:
        return (now - timedelta(days=2)).date()
    local = last_reading.tz_convert(tz)
    end_of_day = local.normalize()
    return (end_of_day - timedelta(days=1)).date()
