"""What every number on the /greenhouse page is: how it is made, from what, and how to read it.

The page shows a balloon per number from this catalogue. The prose lives in
red's translation catalogues (``red/i18n/<lang>.yaml`` → ``greenhouse.explain``);
this module supplies what the prose quotes: the config's coefficients, so a
number quoted is the one the balance uses, and which LetsGrow tags feed each
metric.

``scope`` says where a number is valid, which the page shows as a badge:

- ``spot``: measured at one place in the block (the measuring box, the scale) —
  microclimates elsewhere in the block can differ;
- ``row``: measured at several heights along one row (the multi-height sensors);
- ``block``: an actuator's setting, the same for the whole block;
- ``outside``: the weather station on the roof;
- ``model``: calculated by the balance from the others;
- ``rule``: the grower's rule or a planner's answer.

Visitors never read file names or data-series ids in the prose. A configured
number reads "configured" — written ``[configured](cfg:<group>)`` in the
catalogue — and the page opens the values behind it (:func:`configured`); a
LetsGrow series or module reads by its plain name — ``[…](tag:<tag>)``,
``[…](mod:<role>)`` — with its id in the popup; ``[…](term:<id>)`` explains a
word such as "calibrated". Literature is cited as ``[^id]``.
"""

from __future__ import annotations

import html
import re
from functools import cache
from pathlib import Path

import yaml

from wp6_data.red.greenhouse import physics as P
from wp6_data.red.greenhouse import transpiration as T
from wp6_data.red.greenhouse.config import GreenhouseConfig
from wp6_data.red.greenhouse.state import COLUMNS
from wp6_data.shared import i18n
from wp6_data.shared.i18n import t

PREFIX = "greenhouse.explain"
CFG = "greenhouse.cfg"
FIELDS = ("title", "how", "source", "read")
_LAMP_TAGS = ["lg_assim_light_on", "lg_assim_light_pct"]

#: metric → (scope, LetsGrow tags per device role). The prose is in the catalogue.
ENTRIES: dict[str, tuple[str, list[tuple[str, list[str]]]]] = {
    "t_out": ("outside", [("weather", ["lg_temp_outside"])]),
    "rh_out": ("outside", [("weather", ["lg_rh_outside", "lg_abs_hum_outside"])]),
    "radiation": ("outside", [("weather", ["lg_rad"])]),
    "wind": ("outside", [("weather", ["lg_wind_speed", "lg_wind_dir"])]),
    "t_in": ("spot", [("climate", ["lg_temp_greenhouse"])]),
    "rh_in": ("spot", [("climate", ["lg_rh_greenhouse", "lg_abs_hum_greenhouse"])]),
    "co2": ("spot", [("climate", ["lg_co2"])]),
    "heat_sp": ("block", [("climate", ["lg_heating_setpoint"])]),
    "delta_t": ("model", []),
    "lamps": ("block", [("lamps", _LAMP_TAGS)]),
    "lamp_power": ("model", []),
    "light_sum": ("model", [("weather", ["lg_rad"]), ("lamps", _LAMP_TAGS)]),
    "day_length": ("model", [("weather", ["lg_rad"]), ("lamps", _LAMP_TAGS)]),
    "dark": ("model", []),
    "lamp_h_needed": ("rule", []),
    "lamp_h_longest_day": ("rule", []),
    "pipe_temp": ("block", [("climate", ["lg_pipe_lower", "lg_pipe_growth"])]),
    "pipe_heat": (
        "model",
        [("climate", ["lg_pipe_lower", "lg_pipe_growth", "lg_temp_greenhouse"])],
    ),
    "vent_pos": ("block", [("climate", ["lg_vent_lee", "lg_vent_wind"])]),
    "air_exchange": ("model", []),
    "ventilation": ("model", []),
    "vapour_out": ("model", []),
    "screen_pos": ("block", [("climate", ["lg_energy_curtain"])]),
    "cover": ("model", []),
    "sun": ("model", [("weather", ["lg_rad"])]),
    "residual": ("model", []),
    "transpiration": ("spot", [("water", ["lg_substrate_weight", "lg_irrigation", "lg_drain"])]),
    "evaporation": ("model", []),
    "wake": ("spot", []),
    "weight": ("spot", [("water", ["lg_substrate_weight"])]),
    "irrigation": ("block", [("water", ["lg_irrigation", "lg_irrigation_starts"])]),
    "drain": ("spot", [("water", ["lg_drain"])]),
    "ec_drain": ("spot", [("water", ["lg_drain_ec"])]),
    "crop_water": ("spot", [("water", ["lg_irrigation", "lg_drain", "lg_substrate_weight"])]),
    "humid_h": ("spot", [("climate", ["lg_rh_greenhouse"])]),
    "heat_mj": ("model", []),
    "lamp_h": ("block", [("lamps", _LAMP_TAGS)]),
    "sensors": ("spot", []),
    "microclimate": ("row", []),
}

#: What each "configured" popup lists: the setting's path and its number format.
#: Labels and units live in the catalogue (``greenhouse.cfg.<group>.<field>``);
#: the ventilation curve, the lamps' power, the pipes and the wires' row add rows
#: of their own.
CONFIG_GROUPS: dict[str, list[tuple[str, str]]] = {
    "cover": [
        ("cover.transmission", ".0%"),
        ("cover.u_open", "g"),
        ("cover.u_wind", "g"),
        ("cover.screen_saving", ".0%"),
        ("cover.screen_transmission", ".0%"),
        ("cover.reflected_share", ".0%"),
        ("cover.cover_temperature_share", ".0%"),
        ("cover.condensation_rate", "g"),
    ],
    "ventilation": [],
    "lamps": [("lamps.par", "g"), ("lamps.radiation_eq", "g"), ("lamps.efficacy", "g")],
    "pipes": [],
    "crop_water": [
        ("scale_area_m2", "g"),
        ("transpiration.intercept", "g"),
        ("transpiration.per_sun_w", "g"),
        ("transpiration.per_lamp_w", "g"),
        ("transpiration.per_hd", "g"),
        ("transpiration.per_pipe_w", "g"),
    ],
    "rules": [
        ("advice.light_target_jcm2", "g"),
        ("advice.dark_min_h", "d"),
        ("advice.wake_lamp_h", "g"),
        ("advice.sun_max_w", "g"),
        ("advice.humid_rh", "g"),
        ("advice.humid_hours_target", "g"),
        ("advice.vent_open_pct", "g"),
        ("advice.dry_rh", "g"),
        ("advice.co2_lamp_floor_ppm", "g"),
    ],
    "microclimate": [],
}
PROVENANCE = ("calibrated", "literature", "assumed", "grower", "twin")

#: ``[text](kind:id)`` in catalogue prose: a word with a popup behind it.
TERM = re.compile(r"\[([^\]]+)\]\((cfg|tag|mod|term):([a-z0-9_]+)\)")

REFERENCES = Path(__file__).parent / "references.yaml"


@cache
def references() -> dict[str, dict[str, str]]:
    """The literature the explanations and advice cite as ``[^id]`` (not translated)."""
    raw = yaml.safe_load(REFERENCES.read_text(encoding="utf-8"))["references"]
    return {
        ref_id: {"label": r["label"], "cite": " ".join(r["cite"].split()), "url": r["url"]}
        for ref_id, r in raw.items()
    }


def pipe_label(tag: str, fallback: str) -> str:
    """A heating circuit's name in the current language (the config's label if untranslated)."""
    return i18n.lookup(f"greenhouse.pipe.{tag}") or fallback


def params(cfg: GreenhouseConfig) -> dict:
    """Everything the explanations quote, from the config and the physics' constants."""
    c, v = cfg.cover, cfg.ventilation
    lamps, a, tr = cfg.lamps, cfg.advice, cfg.transpiration
    pipes = "; ".join(
        t(
            f"{PREFIX}.pipe_geometry",
            label=pipe_label(p.tag, p.label),
            diameter_mm=round(p.diameter * 1000),
            length=p.length,
        )
        for p in cfg.pipes
    )
    curve = ", ".join(
        f"{i18n.number(o, '.0%')} → {i18n.number(r * 3600, '.0f')}"
        for o, r in zip(v.opening, v.rate, strict=True)
    )
    return {
        "transmission": c.transmission,
        "u_open": c.u_open,
        "u_wind": c.u_wind,
        "screen_saving": c.screen_saving,
        "screen_transmission": c.screen_transmission,
        "reflected_share": c.reflected_share,
        "curve": curve,
        "par": lamps.par,
        "efficacy": lamps.efficacy,
        "power_w": round(lamps.power_w),
        "radiation_eq": lamps.radiation_eq,
        "pipes": pipes,
        "emissivity": P.PIPE_EMISSIVITY,
        "rho_cp": P.RHO_CP,
        "latent_mj": P.LATENT_HEAT / 1e6,
        "scale_area": cfg.scale_area_m2,
        "quiet_min": int(T.QUIET_AFTER_IRRIGATION.total_seconds() // 60),
        "tr_intercept": tr.intercept,
        "tr_sun": tr.per_sun_w,
        "tr_lamp": tr.per_lamp_w,
        "tr_hd": tr.per_hd,
        "tr_pipe": tr.per_pipe_w,
        "target": a.light_target_jcm2,
        "dark_min": a.dark_min_h,
        "wake": a.wake_lamp_h,
        "sun_max_w": a.sun_max_w,
        "humid_rh": a.humid_rh,
        "humid_hours_target": a.humid_hours_target,
        "co2_floor": a.co2_lamp_floor_ppm,
    }


def _series(role: str, tags: list[str]) -> str:
    """One module's series as the prose names them: plain names, ids behind popups."""
    return t(
        f"{PREFIX}.lg",
        module=f"[{t(f'greenhouse.module.{role}.name')}](mod:{role})",
        tags=", ".join(f"[{t(f'greenhouse.tag.{tag}')}](tag:{tag})" for tag in tags),
    )


def catalogue(cfg: GreenhouseConfig) -> dict[str, dict[str, str]]:
    """Explanation per metric key, in the current language, as the page asks for them."""
    quoted = params(cfg)
    out: dict[str, dict[str, str]] = {}
    for key, (scope, sources) in ENTRIES.items():
        lg = " ".join(_series(role, tags) for role, tags in sources)
        entry = {"scope": scope}
        for field in FIELDS:
            entry[field] = t(f"{PREFIX}.{key}.{field}", lg=lg, **quoted)
        out[key] = entry
    return out


# ---------------------------------------------------------------- configured values
def _value(cfg: GreenhouseConfig, path: str):
    node: object = cfg
    for part in path.split("."):
        node = getattr(node, part)
    return node


def _row(label: str, number: str, unit: str, source: str) -> dict[str, str]:
    space = "" if unit.startswith("%") or not unit else " "
    return {"label": label, "value": f"{number}{space}{unit}", "source": source}


def _extra_rows(group: str, cfg: GreenhouseConfig) -> list[dict[str, str]]:
    """Rows that are not one setting each: the vent curve, the lamps' power, the pipes,
    the multi-height sensors' row."""
    if group == "ventilation":
        v = cfg.ventilation
        return [
            _row(
                t(f"{CFG}.ventilation.point", opening=i18n.number(opening, ".0%")),
                i18n.number(rate * 3600, ".1f"),
                t(f"{CFG}.ventilation.unit"),
                cfg.source_of("ventilation"),
            )
            for opening, rate in zip(v.opening, v.rate, strict=True)
        ]
    if group == "lamps":
        return [
            _row(
                t(f"{CFG}.lamps.power.label"),
                i18n.number(cfg.lamps.power_w, ".0f"),
                t(f"{CFG}.lamps.power.unit"),
                cfg.source_of("lamps.efficacy"),
            )
        ]
    if group == "pipes":
        return [
            _row(
                pipe_label(p.tag, p.label),
                t(f"{CFG}.pipes.value", diameter_mm=round(p.diameter * 1000), length=p.length),
                "",
                cfg.source_of("pipes"),
            )
            for p in cfg.pipes
        ]
    if group == "microclimate":
        mc = cfg.microclimate
        return [
            _row(
                t(f"{CFG}.microclimate.runs.label"),
                t(f"{CFG}.microclimate.runs.{mc.runs}"),
                "",
                cfg.source_of("microclimate.runs"),
            ),
            *(
                _row(
                    w.id,
                    i18n.number(w.at_m, "g"),
                    t(f"{CFG}.microclimate.wire_unit"),
                    cfg.source_of("microclimate.wires"),
                )
                for w in mc.wires
            ),
            *(
                _row(
                    t(f"{CFG}.microclimate.height", h=h),
                    i18n.number(m, "g"),
                    t(f"{CFG}.microclimate.height_unit"),
                    cfg.source_of("microclimate.heights_m"),
                )
                for h, m in sorted(mc.heights_m.items())
            ),
        ]
    return []


def configured(cfg: GreenhouseConfig) -> dict:
    """The values behind every "configured" on the page, and the ids behind plain names.

    ``groups``: per popup, its title and rows (label, value with unit, provenance);
    ``sources``: the provenance words; ``modules`` and ``tags``: the LetsGrow
    modules and series the prose names, so their popups can show the ids.
    """
    groups: dict[str, dict] = {}
    for group, fields in CONFIG_GROUPS.items():
        rows = [
            _row(
                t(f"{CFG}.{group}.{path.rpartition('.')[2]}.label"),
                i18n.number(_value(cfg, path), spec),
                t(f"{CFG}.{group}.{path.rpartition('.')[2]}.unit"),
                cfg.source_of(path),
            )
            for path, spec in fields
        ]
        groups[group] = {"title": t(f"{CFG}.{group}.title"), "rows": rows + _extra_rows(group, cfg)}
    return {
        "groups": groups,
        "sources": {kind: t(f"{CFG}.source.{kind}") for kind in PROVENANCE},
        "modules": {
            role: {
                "name": t(f"greenhouse.module.{role}.name"),
                "about": t(f"greenhouse.module.{role}.about"),
                "device": device,
            }
            for role, device in cfg.devices.model_dump().items()
        },
        "tags": {tag: role for (role, tag) in COLUMNS},
    }


def render_terms(text: str) -> str:
    """Catalogue markup → the page's popup buttons, for prose rendered on the server.

    The browser does the same for the prose it renders (``terms`` in app.js).
    """
    return TERM.sub(
        lambda m: (
            f'<button type="button" class="gh-term" data-kind="{m[2]}" data-id="{m[3]}">'
            f"{html.escape(m[1])}</button>"
        ),
        text,
    )
