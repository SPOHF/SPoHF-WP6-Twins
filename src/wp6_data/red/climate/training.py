"""Training orchestration for red's climate chain.

One entry point, :func:`train_chain`, that fetches, fits and saves the whole
thing. It is deliberately a full refit every time rather than an incremental
update: the fits are cheap, the data grows, and a chain assembled from stages
trained at different times would report a quality none of its parts had.

**Retraining is how this gets better.** Every run re-reads from
``climate_model.training_start`` to now, so each month of new readings widens
the span the model has seen, and the reported skill moves with it. Two things
are surfaced so that improvement is visible rather than implicit:

- :attr:`TrainedChain.span_days` and the row counts, so growth is on the page.
- :attr:`TrainedChain.suggestions` — config that has become improvable, such as
  a wire now reporting heights the config does not declare.

Whether link 3 uses a day-of-year term is **not** config and not a suggestion:
each fit tries both and keeps the better out-of-fold score, so a term that only
starts helping once the wires have seen a winter switches itself on at the next
retrain without anyone remembering to flip anything.

Which greenhouse-level reference to measure per-height deviations against is
**decided here by evidence**: both declared candidates are trained and the one
with the better end-to-end skill wins, with the comparison kept for the page.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from starlette.concurrency import run_in_threadpool

from wp6_data.red.climate import data as climate_data
from wp6_data.red.climate.config import ClimateModelConfig
from wp6_data.red.climate.downscale import DownscaleStats, WireDownscaler
from wp6_data.red.climate.model import (
    MODEL_PATH,
    MODEL_VERSION,
    WEATHER_VARIABLES,
    ClimateModelStats,
    IndoorClimateModel,
    read_artifact,
)
from wp6_data.red.lamp import LampModel, derive_lamp_model
from wp6_data.shared.weather import OpenMeteoClient

# Measurements a wire reports that link 3 can model, in the order they must be
# predicted: temperature first, because humidity's conversion back from moisture
# content needs the predicted temperature at that height.
WIRE_MEASUREMENTS: tuple[str, ...] = ("temp", "hum", "co2", "par")


@dataclass
class TrainedChain:
    """A complete, saved chain plus how it was chosen."""

    trained_at: datetime
    chosen_reference: str
    comparison: dict[str, ClimateModelStats] = field(default_factory=dict)
    downscale: DownscaleStats | None = None
    lamp: LampModel | None = None
    suggestions: list[str] = field(default_factory=list)
    model_version: int = MODEL_VERSION

    @property
    def stats(self) -> ClimateModelStats | None:
        return self.comparison.get(self.chosen_reference)

    @property
    def span_days(self) -> int:
        stats = self.stats
        if stats is None or stats.span[0] is None:
            return 0
        return (stats.span[1] - stats.span[0]).days + 1


def mean_skill(stats: ClimateModelStats, baseline: str = "persistence") -> float:
    """Average skill against ``baseline`` across every (target, horizon) fit.

    The single number used to choose between candidate references. Averaging
    skill rather than R² keeps the comparison in terms of "how much of the
    baseline's error did this remove", which is comparable across targets that
    are individually easy or hard.
    """
    values = [
        fit.stats.skill[baseline] for fit in stats.link2 if baseline in fit.stats.skill
    ]
    return round(float(np.mean(values)), 4) if values else float("-inf")


def choose_reference(comparison: dict[str, ClimateModelStats]) -> str:
    """Pick the greenhouse-level reference to measure deviations against.

    **Coverage first, skill second.** A reference that carries more of the
    declared targets wins outright, because picking on skill alone silently
    drops a target: red's ``s2101`` has no CO₂ sensor, and it edges ``s2103`` on
    mean skill only because its own swing is larger and so leaves more variance
    to explain. Choosing it would have quietly produced a model with no CO₂ in
    it at all while reporting a marginally better number.

    Skill breaks ties between references covering the same targets.
    """
    def rank(key: str) -> tuple[int, float]:
        return len(comparison[key].targets), mean_skill(comparison[key])

    return max(comparison, key=rank)


def config_drift(
    config: ClimateModelConfig, observed: dict[tuple[str, str], list[int]]
) -> list[str]:
    """Wires now reporting heights the config does not declare.

    Config records what each wire was measured to report
    (``docs/red/wire-data-coverage.md``). Sensors come back, so a run that sees
    more than the config admits should say so rather than silently keep
    ignoring the extra heights.
    """
    notes: list[str] = []
    for (wire, measurement), heights in sorted(observed.items()):
        declared = set(config.wire_availability[wire].heights(measurement))
        extra = sorted(set(heights) - declared)
        if extra:
            notes.append(
                f"{wire} now reports {measurement} at height(s) "
                f"{', '.join(f'H{h}' for h in extra)}, which "
                f"climate_model.wire_availability does not declare — "
                f"add them to train on them."
            )
    return notes


async def _fetch_weather(
    config: ClimateModelConfig, client: OpenMeteoClient, end: date
) -> pd.DataFrame:
    return await client.get_hourly(
        list(WEATHER_VARIABLES), start=config.training_start, end=end
    )


async def train_chain(
    config: ClimateModelConfig,
    weather_client: OpenMeteoClient,
    *,
    today: date | None = None,
) -> TrainedChain:
    """Fetch, fit and choose. Returns the chain; the caller saves it.

    Raises ``ValueError`` when an input the chain cannot be built without is
    missing, so a failed run says which piece was absent rather than producing a
    model with a silently empty stage.
    """
    today = today or datetime.now(UTC).date()
    start = datetime.combine(config.training_start, datetime.min.time(), tzinfo=UTC)
    end = datetime.combine(today, datetime.min.time(), tzinfo=UTC) + timedelta(days=1)

    weather = await _fetch_weather(config, weather_client, today)
    if weather.empty:
        raise ValueError("no OpenMeteo weather returned for the training span")

    outdoor = await climate_data.sensor_frames(
        {name: (config.outdoor.device, name) for name in config.outdoor.sensors},
        start, end,
    )
    if not outdoor:
        raise ValueError(f"no readings from {config.outdoor.device} for the span")

    comparison: dict[str, ClimateModelStats] = {}
    models: dict[str, IndoorClimateModel] = {}
    for reference in config.references:
        indoor = await climate_data.sensor_frames(
            {name: (reference.device, sensor)
             for name, sensor in reference.sensors.items()},
            start, end,
        )
        if not indoor:
            continue
        # Link 2's light target is the ABOVE-LAMP sensor: the part of canopy
        # light weather can explain. Predicting the canopy sensor from weather
        # asks the model to forecast an operator's lamp schedule, which it
        # cannot, and which it papers over with a day-of-year term instead
        # (MODEL_PAPER §7.5).
        par = await climate_data.sensor_series(
            config.par.natural.device, config.par.natural.sensor, start, end,
        )
        if not par.empty:
            indoor["par"] = par
        model = IndoorClimateModel(config, reference.key)
        model.link2_sources = {
            **{name: (reference.device, sensor)
               for name, sensor in reference.sensors.items()},
            **({"par": (config.par.natural.device, config.par.natural.sensor)}
               if not par.empty else {}),
        }
        # Ridge fitting is CPU-bound and this runs on the dashboard's event
        # loop; without the threadpool a retrain would stall every other
        # request for the length of the run.
        comparison[reference.key] = await run_in_threadpool(
            model.train, weather, outdoor, indoor
        )
        models[reference.key] = model

    if not comparison:
        raise ValueError("no greenhouse-level reference returned any readings")

    chosen = choose_reference(comparison)
    reference_spec = config.reference(chosen)

    reference_series = await climate_data.sensor_frames(
        {name: (reference_spec.device, sensor)
         for name, sensor in reference_spec.sensors.items()},
        start, end,
    )
    # Link 3's reference stays the canopy sensor — like-for-like with the wire
    # PAR sensors, which hang under the lamps too.
    canopy_par = await climate_data.sensor_series(
        config.par.canopy.device, config.par.canopy.sensor, start, end,
    )
    reference_series["par"] = canopy_par
    natural_par = await climate_data.sensor_series(
        config.par.natural.device, config.par.natural.sensor, start, end,
    )
    lamp = derive_lamp_model(natural_par, canopy_par)

    wire_series: dict[tuple[str, str], dict[str, pd.DataFrame]] = {}
    observed: dict[tuple[str, str], list[int]] = {}
    for wire, availability in sorted(config.wire_availability.items()):
        wire_start = max(
            start,
            datetime.combine(
                availability.available_from, datetime.min.time(), tzinfo=UTC
            ),
        )
        for measurement in WIRE_MEASUREMENTS:
            heights = availability.heights(measurement)
            if not heights:
                continue
            frames = await climate_data.wire_frames(
                wire, measurement, heights, wire_start, end
            )
            if frames:
                wire_series[(wire, measurement)] = frames
                observed[(wire, measurement)] = [
                    int(key.lstrip("h")) for key in frames
                ]

    downscaler = WireDownscaler(config, chosen)
    downscale_stats = (
        await run_in_threadpool(downscaler.train, reference_series, wire_series)
        if wire_series
        else None
    )

    chain = TrainedChain(
        trained_at=datetime.now(UTC),
        chosen_reference=chosen,
        comparison=comparison,
        downscale=downscale_stats,
        lamp=lamp,
        suggestions=_suggestions(config, downscale_stats, observed),
    )
    _save(chain, models[chosen], downscaler)
    return chain


def _suggestions(
    config: ClimateModelConfig,
    downscale: DownscaleStats | None,
    observed: dict[tuple[str, str], list[int]],
) -> list[str]:
    """What a future retrain could do better, given what this one just saw."""
    notes = config_drift(config, observed)
    if downscale is not None and downscale.fits and not downscale.earned_its_place:
        notes.append(
            "No per-height model beat simply using the greenhouse-level "
            "reference. Link 3 is not yet earning its place."
        )
    return notes


def _save(
    chain: TrainedChain, model: IndoorClimateModel, downscaler: WireDownscaler
) -> Path:
    """Persist the chosen chain as one artifact.

    Models live on ephemeral storage, so a restart wipes them and the dashboard
    retrains on boot — the same arrangement as the DLI and blue soil models.
    Deliberately not on the export PVC, which is mounted read-only.
    """
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as handle:
        pickle.dump(
            {
                "version": MODEL_VERSION,
                "chain": chain,
                "link1_models": model.link1_models,
                "link2_models": model.link2_models,
                "climatology": model.climatology,
                "link2_autoregressive": model.link2_autoregressive,
                "link2_exogenous": model.link2_exogenous,
                "link2_sources": model.link2_sources,
                "downscale_models": downscaler.models,
            },
            handle,
        )
    return MODEL_PATH


def load_models(
    config: ClimateModelConfig,
) -> tuple[TrainedChain, IndoorClimateModel, WireDownscaler] | None:
    """Restore the saved chain *and* the fitted models behind it.

    ``load_chain`` returns only the stats a status page needs; this returns the
    objects a prediction needs. Both refuse an artifact from an older era rather
    than mixing eras, so a stale pickle on ephemeral storage degrades to
    "retrain", never to wrong numbers.
    """
    data = read_artifact(MODEL_PATH)
    if data is None:
        return None

    chain = data.get("chain")
    if chain is None:
        return None

    model = IndoorClimateModel(config, chain.chosen_reference)
    model.link1_models = data["link1_models"]
    model.link2_models = data["link2_models"]
    model.climatology = data.get("climatology", {})
    model.link2_autoregressive = data.get("link2_autoregressive", [])
    model.link2_exogenous = data.get("link2_exogenous", [])
    model.link2_sources = data.get("link2_sources", {})
    model.stats = chain.stats

    downscaler = WireDownscaler(config, chain.chosen_reference)
    downscaler.models = data["downscale_models"]
    downscaler.stats = chain.downscale
    return chain, model, downscaler


def load_chain() -> TrainedChain | None:
    """The saved chain, or ``None`` when absent or from an older era."""
    data = read_artifact(MODEL_PATH)
    return data.get("chain") if data else None
