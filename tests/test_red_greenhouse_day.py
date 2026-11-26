"""The greenhouse page's data: transpiration, planner, light, advice and a whole day."""

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from wp6_data.red.greenhouse import advice as A
from wp6_data.red.greenhouse import day as D
from wp6_data.red.greenhouse import explain, planner
from wp6_data.red.greenhouse import state as S
from wp6_data.red.greenhouse import transpiration as T
from wp6_data.red.greenhouse.config import load_greenhouse
from wp6_data.shared import i18n

CFG = load_greenhouse(Path(__file__).parents[1] / "src/wp6_data/red/metadata.yaml")
RED_I18N = Path(__file__).parents[1] / "src/wp6_data/red/i18n"


@pytest.fixture(autouse=True)
def _catalogues():
    """Advice and explanations read red's catalogues (English unless a test switches)."""
    i18n.load(i18n.SHARED_DIR, RED_I18N)
TZ = "Europe/Amsterdam"
DAY = date(2026, 1, 14)


def _index(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    return pd.date_range(start, end, freq="5min", inclusive="left")


# ------------------------------------------------------------------ counters
@pytest.mark.parametrize("reset_hour", [23, 0])
def test_counter_totals_read_the_value_before_the_reset(reset_hour):
    """The total is read where the counter drops, whichever clock it resets on."""
    start = pd.Timestamp(DAY, tz=TZ) - timedelta(hours=2)
    idx = _index(start, start + timedelta(days=2))
    reset = pd.Timestamp(DAY, tz=TZ) + timedelta(hours=reset_hour if reset_hour else 24)
    prev_reset = reset - timedelta(days=1)
    values = []
    for t in idx:
        anchor = (
            reset
            if t >= reset
            else prev_reset
            if t >= prev_reset
            else prev_reset - timedelta(days=1)
        )
        values.append(round((t - anchor).total_seconds() / 3600 * 0.1, 4))  # 0.1 l/m² per hour
    totals = T.counter_totals(pd.Series(values, index=idx))
    assert totals[pd.Timestamp(DAY)] == pytest.approx(2.4 - 0.1 / 12, abs=0.02)


def test_quiet_rate_is_weight_loss_over_the_scale_area():
    idx = _index(pd.Timestamp(DAY, tz=TZ), pd.Timestamp(DAY, tz=TZ) + timedelta(hours=4))
    kg_per_h = 0.4
    weight = pd.Series(30 - kg_per_h * np.arange(len(idx)) / 12, index=idx)
    irrigation = pd.Series(0.0, index=idx)
    e = T.quiet_rate(weight, irrigation, CFG)
    assert e.dropna().to_numpy() == pytest.approx(kg_per_h / CFG.scale_area_m2)


def test_quiet_rate_survives_a_day_without_irrigation():
    """A changeover day has no pulse at all; the slope is still transpiration."""
    idx = _index(pd.Timestamp(DAY, tz=TZ), pd.Timestamp(DAY, tz=TZ) + timedelta(hours=2))
    weight = pd.Series(30.0 - 0.01 * np.arange(len(idx)), index=idx)
    e = T.quiet_rate(weight, pd.Series(0.0, index=idx), CFG)
    assert e.notna().any()


def test_quiet_rate_skips_the_slots_after_a_pulse():
    idx = _index(pd.Timestamp(DAY, tz=TZ), pd.Timestamp(DAY, tz=TZ) + timedelta(hours=4))
    irrigation = pd.Series(np.where(idx >= idx[24], 0.3, 0.0), index=idx)
    weight = pd.Series(30.0, index=idx)
    e = T.quiet_rate(weight, irrigation, CFG)
    after = (idx >= idx[24]) & (idx < idx[24] + T.QUIET_AFTER_IRRIGATION)
    assert e[after].isna().all()


def test_day_series_scales_the_model_to_the_water_balance():
    idx = _index(pd.Timestamp(DAY, tz=TZ), pd.Timestamp(DAY, tz=TZ) + timedelta(days=1))
    measured = pd.Series(np.where(idx.hour < 6, 0.04, np.nan), index=idx)
    modelled = pd.Series(0.1, index=idx)
    out = T.day_series(measured, modelled, total=2.4)
    assert out["transpiration"].sum() / 12 == pytest.approx(2.4)
    assert (out.loc[idx.hour < 6, "source"] == "scale").all()


def test_wake_time_is_the_half_response():
    trigger = pd.Timestamp(DAY, tz=TZ) + timedelta(hours=1)
    idx = _index(trigger - timedelta(hours=3), trigger + timedelta(hours=5))
    minutes = (idx - trigger).total_seconds() / 60
    e = pd.Series(np.where(minutes < 0, 0.04, 0.04 + 0.06 * np.clip(minutes / 60, 0, 1)), index=idx)
    woke = T.wake_time(e, trigger)
    assert woke is not None
    assert timedelta(minutes=20) <= woke["time"] - trigger <= timedelta(minutes=40)


def test_no_wake_without_a_rise():
    trigger = pd.Timestamp(DAY, tz=TZ) + timedelta(hours=1)
    idx = _index(trigger - timedelta(hours=3), trigger + timedelta(hours=5))
    assert T.wake_time(pd.Series(0.04, index=idx), trigger) is None


# ------------------------------------------------------------------ planner
K = CFG.lamps.radiation_eq


def test_plan_keeps_the_dark_window_and_reaches_the_target():
    sun = np.zeros(24)
    price = np.arange(24, dtype=float)
    target = 10 * K
    u = planner.plan_day(sun, price, target, K, dark_min=6, wake=0.5)
    assert u is not None
    lit = u > 0.5
    eff = u.sum() - 0.5 * planner.starts(u)
    assert eff * K >= target - 1e-6
    runs, run = [], 0
    for x in ~lit:
        run = run + 1 if x else 0
        runs.append(run)
    assert max(runs) >= 6


def test_wake_cost_stops_a_split_that_saves_too_little():
    sun = np.zeros(24)
    price = np.full(24, 100.0)
    price[6] = 99.0  # a hair cheaper: not worth a second switch-on
    # 8.5 effective hours: one 9-hour block fits exactly; splitting off the
    # cheap hour costs a whole extra lamp-hour of wake-up
    u = planner.plan_day(sun, price, 8.5 * K, K, dark_min=6, wake=0.5)
    assert planner.starts(u) == 1
    assert u.sum() == 9


def test_lamp_hours_needed_fill_the_gap_to_the_target_plus_one_wake_up():
    a = CFG.advice
    sun = np.zeros(24)
    sun[10:14] = 100.0  # 400 J/cm² of sun, all below the lamp cut-off
    gap_h = (a.light_target_jcm2 - sun.sum()) / K
    need = A.lamp_hours_needed(sun, CFG)
    assert need == np.ceil(gap_h + a.wake_lamp_h)


def test_no_lamp_hours_needed_when_the_sun_reaches_the_target():
    sun = np.zeros(24)
    sun[8:18] = CFG.advice.light_target_jcm2 / 10
    assert A.lamp_hours_needed(sun, CFG) == 0


def test_longest_day_keeps_the_rest_and_skips_strong_sun():
    a = CFG.advice
    sun = np.zeros(24)
    sun[11:14] = a.sun_max_w * A.J_PER_W_HOUR + 1  # three hours of strong sun
    assert A.longest_day_lamp_hours(sun, CFG) == 24 - 3 - a.dark_min_h


# ------------------------------------------------------------------ light period
def _light_frame(lamps_on: tuple[int, int], sun: tuple[int, int]) -> pd.DataFrame:
    """Two days and margins of 5-minute lamps and radiation, the same each day."""
    start, end = S.window(DAY, TZ)
    idx = _index(start, end)
    hour = idx.hour + idx.minute / 60
    lo, hi = lamps_on
    on = (hour >= lo) | (hour < hi) if lo > hi else (hour >= lo) & (hour < hi)
    f = pd.DataFrame(index=idx)
    f["lamp_on"] = np.where(on, 1.0, 0.0)
    f["lamp_pct"] = 100.0
    f["radiation"] = np.where((hour >= sun[0]) & (hour < sun[1]), 200.0, 0.0)
    return f


def test_light_period_counts_sun_and_lamps_in_the_dark():
    # lamps 23:00-15:00 across midnight, sun 08:30-16:30: the winter schedule
    light = A.light_period(_light_frame((23, 15), (8.5, 16.5)), pd.Timestamp(DAY, tz=TZ))
    assert light["sun_h"] == pytest.approx(8.0)
    assert light["lamp_only_h"] == pytest.approx(8.5 + 1.0)  # 00:00-08:30 and 23:00-24:00
    assert light["light_h"] == pytest.approx(17.5)
    assert light["longest_dark_h"] == pytest.approx(6.5)  # 16:30-23:00


def test_longest_dark_runs_across_midnight():
    """A summer night split by midnight is one rest, not two short ones."""
    light = A.light_period(_light_frame((0, 0), (5, 21.5)), pd.Timestamp(DAY, tz=TZ))
    assert light["dark_h"] == pytest.approx(7.5)
    assert light["longest_dark_h"] == pytest.approx(7.5)


# ------------------------------------------------------------------ a whole day
def _synthetic_day() -> pd.DataFrame:
    start, end = S.window(DAY, TZ)
    idx = _index(start, end)
    hour = idx.hour + idx.minute / 60
    day_start = pd.Timestamp(DAY, tz=TZ)
    f = pd.DataFrame(index=idx)
    f["t_in"] = 20.0
    f["rh_in"] = 80.0
    f["ah_in"] = 13.8
    f["hd_in"] = 3.4
    f["co2"] = 500.0
    f["heat_sp"] = 19.0
    f["vent_sp"] = 22.0
    f["vent_lee"] = np.where((hour > 10) & (hour < 14), 30.0, 0.0)
    f["vent_wind"] = f["vent_lee"]
    f["screen_pct"] = np.nan
    f["blackout_pct"] = np.nan
    f["lg_pipe_lower"] = 50.0
    f["lg_pipe_growth"] = 40.0
    f["lg_pipe_lower_calc"] = 50.0
    f["lg_pipe_growth_calc"] = 40.0
    f["lamp_on"] = np.where(hour < 16, 1.0, 0.0)
    f["lamp_pct"] = np.where(hour < 16, 100.0, 0.0)
    f["t_out"] = 3.0
    f["rh_out"] = 90.0
    f["ah_out"] = 5.3
    f["radiation"] = np.clip(250 * np.sin((hour - 8.5) / 8 * np.pi), 0, None)
    f["wind"] = 2.0
    f["wind_dir"] = 250.0
    f["rain"] = 0.0
    f["ec_irrigation"] = 2.9
    f["ec_drain"] = 4.0
    # irrigation: pulses every 30 min from 06:00 to 15:00, counter resets at midnight
    since_midnight = ((idx - idx.normalize()).total_seconds() / 3600).to_numpy()
    pulses = np.floor(np.clip(since_midnight - 6, 0, 9) * 2)
    f["irrigation"] = np.where(since_midnight >= 6, 0.2 * (pulses + 1), 0.0)
    f["drain"] = f["irrigation"] * 0.3
    f["starts"] = np.where(since_midnight >= 6, pulses + 1, 0.0)
    f["weight"] = 30 - 0.03 * ((idx - day_start).total_seconds() / 3600) % 5
    return f


def test_build_day_returns_every_step_flow_and_advice():
    f5 = _synthetic_day()
    out = D.build_day(f5, DAY, CFG, TZ, 51.0, 6.6)
    assert len(out["steps"]) == 96
    first = out["steps"][0]
    assert set(D.FLOW_FIELDS) <= set(first["flows"])
    assert first["state"]["screen"] is None  # curtain not logged in this day
    ids = {a["id"] for a in out["advice"]}
    assert {"light_sum", "heat_vented", "screen", "humidity", "dark"} <= ids
    components = {a["component"] for a in out["advice"]}
    assert components <= {"lamps", "pipes", "vents", "screen", "crop", "substrate"}
    f = out["summary"]["flows_mj"]
    gains = f["sun"] + f["lamps"] + f["pipes"]
    losses = f["cover"] + f["ventilation"] + f["evaporation"]
    assert f["residual"] == pytest.approx(gains - losses, abs=0.01)
    summary = out["summary"]
    assert summary["light_h"] == pytest.approx(summary["sun_h"] + summary["lamp_only_h"])
    assert not any("eur" in k for k in summary)
    assert all("eur" not in a["impact"] for a in out["advice"])


def test_a_day_letsgrow_has_not_delivered_is_the_sun_alone():
    """The multi-height sensors run ahead: such a day is the house with only the sun in it."""
    out = D.bare_day(DAY, CFG, TZ, 51.0, 6.6)
    assert out["letsgrow"] is False
    assert len(out["steps"]) == int(pd.Timedelta(days=1) / pd.Timedelta(S.STEP))
    for step in out["steps"]:
        assert set(step["state"]) == set(D.STATE_FIELDS)
        assert set(step["flows"]) == set(D.FLOW_FIELDS)
        assert all(v is None for v in (*step["state"].values(), *step["flows"].values()))
    elevations = [step["sun_el"] for step in out["steps"]]
    assert min(elevations) < 0 < max(elevations)
    assert out["summary"]["sunrise"] < out["summary"]["sunset"]
    assert out["advice"] == []
    assert out["notes"] == [i18n.t("greenhouse.note.not_delivered")]


def test_a_bare_day_has_the_shape_of_a_delivered_one():
    """So the page draws it with the same code: nothing it reads is missing."""
    built = D.build_day(_synthetic_day(), DAY, CFG, TZ, 51.0, 6.6)
    bare = D.bare_day(DAY, CFG, TZ, 51.0, 6.6)
    assert set(built) <= set(bare)
    assert set(built["summary"]) <= set(bare["summary"])
    assert set(built["summary"]["flows_mj"]) == set(bare["summary"]["flows_mj"])
    assert set(built["steps"][0]) == set(bare["steps"][0])
    assert bare["params"] == built["params"]


def test_what_if_day_closing_the_screen_saves_heat():
    f5 = _synthetic_day()
    w = D.what_if_day(f5, DAY, CFG, TZ, screen_dark=1.0)
    assert w["heat_mj_whatif"] < w["heat_mj"]
    assert len(w["series"]["t"]) == 96


def test_what_if_rejects_an_unknown_lamp_setting():
    with pytest.raises(ValueError):
        D.what_if_day(_synthetic_day(), DAY, CFG, TZ, lamps="plan")


# ------------------------------------------------------------------ explanations
def test_every_explanation_says_how_from_what_and_how_to_read_it():
    notes = explain.catalogue(CFG)
    scopes = {"spot", "row", "block", "outside", "model", "rule"}
    for key, n in notes.items():
        assert {"title", "scope", "how", "source", "read"} <= set(n), key
        assert n["scope"] in scopes, key
        assert all(n[f].strip() for f in ("how", "source", "read")), key


def test_explanations_quote_the_coefficients_the_balance_uses():
    notes = explain.catalogue(CFG)
    assert f"{CFG.cover.u_open:g}" in notes["cover"]["how"]
    assert f"{CFG.lamps.radiation_eq:g}" in notes["light_sum"]["how"]
    # the module is named plainly; its device id sits behind the popup
    assert "](mod:weather)" in notes["t_out"]["source"]


def test_latest_day_is_the_day_before_the_last_reading():
    last = pd.Timestamp("2026-11-23 23:00", tz="UTC")
    assert D.latest_day(pd.Timestamp("2026-11-25", tz=TZ), last, TZ) == date(2026, 11, 23)
