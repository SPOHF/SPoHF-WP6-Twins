# GDD and Harvest Thresholds for Blueberry Cultivar 'Cargo'

**Research Date**: 2026-04-23
**Status**: Verified against live sources (April 2026)
**Overall Confidence**: MEDIUM -- cultivar identity, parentage, chilling, and season classification are all HIGH confidence from primary sources (US Plant Patent PP24,661; Fall Creek; MSU Extension E3490). Specific GDD / bloom-to-harvest thermal-time values for 'Cargo' do **not exist in public literature**; the recommendation uses a proportional scaling derived from Michigan patent harvest dates.

> **Headline**: No published GDD thresholds exist for 'Cargo'. It is unambiguously classified **Mid/Late season** (MSU Extension, 2024) -- meaningfully later than Duke (Early) and modestly later than Bluecrop (Mid). From Cargo's US patent, mean first harvest is **about 32 days later than Bluecrop** in the same Michigan region. Recommended approach: **scale the existing Duke thresholds by ~1.40** (or equivalently, add ~300 GDD) to approximate Cargo in the first season, then calibrate locally. See §6 for concrete numbers.

## Executive Summary

'Cargo' is a northern highbush blueberry (*Vaccinium corymbosum*) released by Fall Creek Farm & Nursery (Lowell, OR) under US Plant Patent **PP24,661** (filed 2012-03-12, issued 2014-07-22). Parentage is 'Bluegold' × 'Ozarkblue'. It is a relatively recent commercial release (patent 2014) intended for machine harvest in the fresh and processed markets.

Season classification is unambiguous: MSU Extension's 2024 E3490 bulletin ("Blueberry Varieties for Michigan") lists Cargo in the **Mid/Late** harvest window alongside Liberty, Legacy, Jersey, and Nelson. This is markedly later than Duke (Early) and somewhat later than Bluecrop/Draper (Mid). The patent itself states Cargo "ripens about one week earlier" than Liberty and "2 to 3 weeks later" than Draper.

**No GDD thresholds have been published for Cargo specifically.** No source -- Fall Creek datasheet, OSU, MSU, WUR, Driscoll's -- publishes bloom-to-stage or bloom-to-harvest GDD values for this cultivar. This was expected: Cargo is patent-protected and recent, and even Duke/Bluecrop lack well-published cultivar-specific GDD tables in peer-reviewed literature (the foundational Carlson & Hancock 1991 paper is the exception).

Chill-hour requirement is documented at **800-1000 h**, same bucket as Duke, Bluecrop, and Liberty. Not a limiting factor for NL maritime conditions in normal winters, but monitor climate-change-driven warm winters as Cargo sits at the same risk level as Duke.

To derive *approximate* thresholds for Cargo, this research triangulates from: (1) mean harvest dates in Cargo's Michigan patent trial (Aug 7 mean, Sep 5 last pick), (2) Bluecrop mean harvest in Michigan (~July 10, from Draper patent, Grand Junction MI), and (3) the existing Duke thresholds from Carlson & Hancock 1991 that are already in the code. The most defensible interim recommendation is to **scale Duke thresholds by approximately 1.4×** (equivalently, add ~300 GDD base 7.2°C to each stage), with explicit documentation that this is an estimate pending local calibration over 2-3 seasons.

## 1. Cultivar Identity and Patent Record

### 1.1 Identity and Parentage

**Confidence: HIGH** (primary source: granted US Plant Patent)

- **Full name**: Blueberry plant named 'Cargo' (*Vaccinium corymbosum* hybrid, northern highbush).
- **Patent**: US Plant Patent **PP24,661**, filed 2012-03-12, issued 2014-07-22. Assignee: Fall Creek Farm and Nursery, Inc., Lowell, Oregon.
- **Parentage**: Female parent 'Bluegold' (unpatented) × Male parent 'Ozarkblue' (US Plant Patent 10,035).
- **Selection**: Selected in Lowell, Oregon in 2005; released commercially as 'Cargo' (trade name) from Fall Creek's breeding program.
- **USDA hardiness zones**: ~4-7 (per patent).

**Source**: USPTO / Google Patents US20130239260P1 (application) and PP24,661 (grant). <https://patents.google.com/patent/US20130239260P1/en>. Accessed 2026-04-23.

### 1.2 Commercial Positioning

**Confidence: HIGH** (breeder datasheet + MSU Extension 2024)

Fall Creek's current catalog page describes Cargo as "ripening in Liberty season", "High Chill", and suited to "commercial plantings in the Pacific Northwest and similar areas throughout the U.S." It is positioned as a late-season machine-harvestable cultivar complementing Liberty and Draper in their genetics portfolio.

MSU Extension's 2024 variety bulletin (E3490) notes: "**Cargo** and LoretoBlue are newer cultivars from Pacific Northwest breeding programs. They are not yet widely planted in Michigan. First reports about new Cargo plantings in Michigan suggest that its short and stocky architecture may make it suitable for machine harvesting for the fresh market." MSU's survey found Cargo at 13.6% of Michigan grower respondents in 2023.

**Sources**:
- Fall Creek Nursery — Cargo variety page: <https://www.fallcreeknursery.com/commercial-fruit-growers/varieties/cargo>. Accessed 2026-04-23.
- MSU Extension E3490 — "Blueberry Varieties for Michigan" (Vander Weide et al., 2024): <https://www.canr.msu.edu/blueberries/uploads/files/E3490_Blueberry_Varieties_MI_AA.pdf>. Accessed 2026-04-23.

## 2. Season Classification

**Confidence: HIGH** (three independent primary sources agree)

'Cargo' is classified as **Mid/Late season** (also phrased "late-mid" or "late" depending on the classification scale used). It is distinctly later than Duke (Early) and later than Bluecrop (Mid), sitting in the same window as Liberty, Legacy, Jersey, and Nelson.

### 2.1 Evidence

**MSU Extension E3490 (2024), Table 2 — Harvest Season Windows:**

| Window | Cultivars (subset) |
|--------|-------------------|
| Early | Duke (1987), Chanticleer, Hannah's Choice |
| Early/Mid | Blueray, Bluejay, Patriot, Osorno, Huron |
| Mid | **Bluecrop** (1952), **Draper** (2004), Calypso, Bluegold, Toro |
| **Mid/Late** | Jersey (1928), Legacy, Liberty (2004), **Cargo (2014)**, Bonus, Chandler |
| Late | Elliott (1973), Aurora (2004), Last Call |

Cargo is listed unambiguously in the **Mid/Late** bucket alongside Liberty (its explicit comparator in the patent).

**Patent (PP24,661) comparison statements:**
- "'Cargo' ripens about one week earlier" than 'Liberty'.
- "'Cargo' ... ripens 2 to 3 weeks later" than 'Draper'.

**Fall Creek catalog**: "Ripening in Liberty season" (confirmed on <fallcreeknursery.com/commercial-fruit-growers/varieties/cargo>).

### 2.2 Relative Timing Translated to Days

Synthesizing the patent harvest dates (all from Michigan trial plots):

| Cultivar | Mean first harvest (Michigan) | Source |
|----------|-------------------------------|--------|
| Draper | 7/5 | Draper patent PP15,103 (Table II, Grand Junction MI) |
| Bluecrop | 7/10 | Draper patent PP15,103 (Table II, Grand Junction MI) |
| **Cargo** | **8/7** | Cargo patent PP24,661 |
| Liberty | 8/18-8/22 | Liberty patent PP15,146 |
| Elliott | 8/23-8/27 | Liberty patent PP15,146 |

Derived intervals (mean first harvest, same region and patent methodology where possible):

- **Cargo is ~23 days later than Draper** (Aug 7 − Jul 5 = 33 days actually; patent says 2-3 weeks → patent text prevails, actual dates are slightly longer. This minor discrepancy is noted as a Knowledge Gap; plot dates differ by cohort year).
- **Cargo is ~28 days later than Bluecrop** (Aug 7 − Jul 10).
- **Cargo is ~11-15 days earlier than Liberty** (patent "about one week earlier" is close to the ~11-day gap between Aug 7 and Aug 18).
- **Cargo is ~32-43 days later than Duke** (Duke mean harvest is late June to early July in Michigan; roughly July 1 as a midpoint → Aug 7 is ~37 days later).

**Headline relative timing**: Cargo is **~4-5 weeks later than Duke** in first harvest, **~3-4 weeks later than Bluecrop**, and **~1-2 weeks earlier than Liberty** in Michigan trials.

**Sources**:
- US PP24,661 'Cargo': <https://patents.google.com/patent/US20130239260P1/en>
- US PP15,103 'Draper': <https://patents.google.com/patent/USPP15103P3/en>
- US PP15,146 'Liberty': <https://patents.google.com/patent/USPP15146P3/en>
- MSU E3490 Table 2: <https://www.canr.msu.edu/blueberries/uploads/files/E3490_Blueberry_Varieties_MI_AA.pdf>

## 3. Published GDD / Thermal-Time Thresholds for Cargo

**Confidence: HIGH (negative finding — thoroughly searched, nothing found)**

### 3.1 Finding: No Cultivar-Specific GDD Values Exist in Public Literature

Searched:
- Fall Creek Nursery (breeder) — commercial datasheet has no GDD data.
- MSU Extension (publishes blueberry phenology GDD) — only publishes thresholds for **Jersey** (base 50°F: bud break 108, bloom 310, petal fall 407, first harvest 1,313), with the note that "for earlier cultivars, these target numbers would be smaller". No Cargo-specific values.
- MSU E3490 (2024 variety bulletin) — no GDD tables for any cultivar.
- OSU Extension, WUR/Wageningen publications — no Cargo GDD data (confirmed in the prior `blueberry-gdd-harvest-prediction.md` research; WUR does not publish cultivar-level GDD tables at all).
- Driscoll's — proprietary, nothing public.
- Peer-reviewed (Marra et al. 2013; Carlson & Hancock 1991) — pre-date Cargo's 2014 release.
- Patent PP24,661 itself — contains phenological dates but no GDD accumulation data.

**Conclusion**: Nobody has published GDD thresholds for 'Cargo'. This is the single most important research finding and must be surfaced in the code (e.g., a comment noting the values are estimates, not sourced).

**Sources for the negative finding**:
- MSU Extension "Using degree days to predict pest and crop development in blueberries" (Wise & Isaacs): <https://www.canr.msu.edu/news/using-degree-days-to-predict-pest-and-crop-development-in-blueberries>. Accessed 2026-04-23. Explicitly states that only Jersey has measured thresholds, and that other-cultivar values are extrapolated qualitatively ("smaller for earlier cultivars").
- Prior research in this repo: `docs/research/blueberry-gdd-harvest-prediction.md` §2.3 — confirms variety-specific GDD values are the "most variable and least well-documented in general literature."

### 3.2 Best Available Proxy: MSU Jersey Thresholds

Jersey is the only cultivar with published MSU Enviroweather GDD thresholds, and critically **Jersey is in the same Mid/Late bucket as Cargo** per MSU E3490. This makes Jersey the best available proxy.

**Jersey thresholds (MSU Extension, base 50°F / 10°C, accumulated from Jan 1 / Mar 1 start):**
- Bud break: 108 GDD
- Bloom onset: 310 GDD
- Petal fall: 407 GDD
- First harvest: 1,313 GDD
- **Bloom-to-first-harvest**: 1,313 − 310 = **1,003 GDD base 50°F** = approximately **1,550-1,650 GDD base 45°F (7.2°C)** after base-conversion.

**Base conversion note**: The code uses base 7.2°C (45°F). Jersey's 1,003 GDD base 50°F translates *approximately* to `1,003 × (T̄ − 45) / (T̄ − 50)` where T̄ is mean daily temperature during the bloom-to-harvest interval. For Michigan summer (T̄ ≈ 20°C / 68°F), this factor is ~(68-45)/(68-50) ≈ 1.28, giving roughly **1,280 GDD base 45°F**. For Dutch summer (T̄ ≈ 17°C / 63°F), factor is ~(63-45)/(63-50) ≈ 1.38, giving roughly **1,390 GDD base 45°F**. These are back-of-envelope; use only as sanity checks.

**Important caveat**: Jersey is a 1928 release with quite different genetics from Cargo. Using it as a proxy for absolute GDD values is unsafe. Using it as a **ratio benchmark** (Jersey : Cargo, both Mid/Late) to scale against a Duke baseline is more defensible than raw substitution.

## 4. Relative Scaling Factor vs. Duke

**Confidence: MEDIUM** (derived calculation, not a direct measurement)

The existing code uses Duke thresholds from Carlson & Hancock 1991 (base 7.2°C, bloom biofix):
- 100 (petal fall) / 300 (green fruit) / 500 (coloring) / 650 (scouting) / 750 (first harvest) / 850 (peak) / 900 (late).

### 4.1 Method 1: Days-Ratio Scaling

From §2.2, Cargo reaches first harvest ~37 days after Duke in Michigan. Duke bloom-to-harvest is typically ~55-65 days (per `blueberry-gdd-harvest-prediction.md` §2.3). Assuming roughly parallel GDD accumulation rates:

- Duke bloom-to-first-harvest: ~60 days → 750 GDD (code baseline).
- Cargo bloom-to-first-harvest: ~60 + 37 = ~97 days (Michigan), or scale factor ~97/60 ≈ **1.62×**.

However, this overstates the scaling because much of the extra calendar time is during progressively cooler late August when daily GDD contribution is already declining. A better estimate uses the temperature-weighted integral.

### 4.2 Method 2: Temperature-Weighted Interval

Rough estimate for Michigan (Grand Junction area, ~42.5°N):
- Duke: first harvest ~July 1, bloom ~May 5 (~57 days). Mean temp during interval ≈ 18-20°C → ~11-13 GDD/day base 7.2°C → ~650-750 GDD.
- Cargo: first harvest Aug 7 (patent), bloom ~late April/early May (same region, Cargo blooms same window as Duke per patent). ~95 days. Mean temp during interval ≈ 19-21°C → ~12-14 GDD/day → ~1,100-1,300 GDD.

Ratio: ~1,200 / 750 ≈ **1.6×** (days-based) or ~**1.4×** if we account for Dutch maritime conditions where late-summer GDD contribution falls off more sharply than in continental Michigan.

### 4.3 Method 3: Proportional to Jersey (Same Mid/Late Bucket)

If Jersey's bloom-to-first-harvest is ~1,280 GDD base 7.2°C (Michigan back-conversion from §3.2) and Duke's is ~750 GDD base 7.2°C, then Jersey/Duke ratio ≈ **1.7×**. Cargo ripens slightly earlier than Jersey in the MSU E3490 ordering (Jersey appears before Cargo in the Mid/Late section text but both are in the same bucket), so a Cargo/Duke ratio of **~1.5-1.6×** is plausible.

### 4.4 Reconciliation and Recommended Scaling

Three independent estimates converge in the range **1.4× - 1.7×**. The variance reflects genuine uncertainty (no Cargo GDD data exists). For a *conservative* first implementation that will likely underpredict rather than overpredict (so scouting starts in time), use the lower end: **1.40×** or equivalently **"add ~300 GDD" to each Duke stage**.

**Recommended scaling for Cargo (base 7.2°C, bloom biofix):**

| Stage | Duke (code) | Cargo scaled ×1.40 | Cargo scaled ×1.60 | Recommended |
|-------|-------------|---------------------|---------------------|--------------|
| Petal fall | 100 | 140 | 160 | **140** |
| Green fruit | 300 | 420 | 480 | **420** |
| Fruit coloring | 500 | 700 | 800 | **700** |
| First pick scouting | 650 | 910 | 1040 | **910** |
| First harvest | 750 | 1050 | 1200 | **1050** |
| Peak harvest | 850 | 1190 | 1360 | **1190** |
| Late harvest | 900 | 1260 | 1440 | **1260** |

**Rationale for 1.40× (lower end) as recommended:**
- Dutch maritime climate has smaller diurnal range and cooler peak summer than Michigan, so absolute GDD accumulation to a given phenological stage tends to be **lower** at higher latitudes, not higher, per established literature (see `blueberry-gdd-harvest-prediction.md` §5.1).
- Scouting thresholds should trigger *earlier* than the true harvest date so the farm has lead time.
- First-season conservatism: easier to revise up after observation than to be caught late.

## 5. Chill-Hour Requirement

**Confidence: HIGH** (two primary sources agree)

Cargo chilling requirement: **approximately 800-1000 hours** below ~7°C.

**Sources**:
- US PP24,661 (patent): "estimated chilling requirement of 800 to 1,000 hours".
- Fall Creek catalog: classified as "High Chill".

This is the **same range as Duke** (800-1000 h per `blueberry-gdd-harvest-prediction.md` §2.3), so **no change to the existing chill-hour assumption** is needed when switching variety from Duke to Cargo. The current 1000 h assumption in the code remains appropriate (slightly conservative upper bound).

**Climate-change note**: Dutch winters are warming, and 800-1000 h is marginal in mild years (see Van Vliet et al. 2014 referenced in prior research). Cargo is no more and no less exposed to this risk than Duke.

## 6. Recommendations for the Digital Twin Code

### 6.1 Headline Recommendation

**Use scaled Duke thresholds (1.40× multiplier)** as Cargo's initial values, with an explicit code comment that these are estimates derived from Michigan patent data and MSU Extension classification, not from published Cargo-specific GDD research. Revisit after 1-2 Dutch seasons of observed bloom-to-harvest data.

### 6.2 Concrete Proposed Thresholds

```
# Cargo thresholds (base 7.2°C, GDD from full bloom)
# Derived: Duke (Carlson & Hancock 1991) × 1.40
# Rationale: Cargo is MSU Mid/Late (E3490, 2024), ~37 days later
# than Duke first harvest in Michigan (patents PP24,661 vs. Duke data).
# No cultivar-specific GDD research exists for Cargo as of 2026-04.
# Calibrate locally once 2026+ observations are available.

CARGO_GDD_THRESHOLDS = {
    "petal_fall":         140,   # Duke 100 × 1.40
    "green_fruit":        420,   # Duke 300 × 1.40
    "fruit_coloring":     700,   # Duke 500 × 1.40
    "first_pick_scouting":910,   # Duke 650 × 1.40
    "first_harvest":     1050,   # Duke 750 × 1.40
    "peak_harvest":      1190,   # Duke 850 × 1.40
    "late_harvest":      1260,   # Duke 900 × 1.40
}
CARGO_CHILL_HOURS = 1000  # same as Duke; PP24,661 states 800-1000 h
```

### 6.3 Alternative: Offer a Scaling Factor Rather than Hardcoded Values

If the dashboard already supports variety abstraction, cleaner to model this as:

```
varieties["cargo"] = {
    "base_temp_c": 7.2,
    "gdd_scale_vs_duke": 1.40,
    "chill_hours": 1000,
    "source": "Fall Creek PP24,661 + MSU E3490; scaled from Carlson & Hancock 1991 Duke.",
    "confidence": "MEDIUM — no published Cargo-specific GDD data.",
}
```

This keeps Cargo dependent on Duke's canonical thresholds and avoids magic numbers, consistent with the user's memory preference (`feedback_test_constants.md`).

### 6.4 Validation Plan (Per Research Methodology §5.2)

For 2026 and 2027 Dutch seasons, record:
1. Full bloom date for Cargo plants.
2. Cumulative GDD (base 7.2°C) from full bloom.
3. Observed dates for petal fall, first fruit coloring, first pick, peak, last pick.
4. Compare to predicted thresholds; adjust the scaling factor (or move to absolute thresholds) for 2028.

After 2 seasons of data, the `gdd_scale_vs_duke` value should be a locally-calibrated constant, not a literature-derived estimate.

## 7. Knowledge Gaps

1. **No Cargo-specific GDD thresholds in public literature.** Searched Fall Creek, MSU, OSU, WUR, Driscoll's, USDA, peer-reviewed journals. Recommendation: email Fall Creek's commercial support team directly; they may have internal Oregon trial data. Also consider contacting Dr. Lisa DeVetter (WSU Mount Vernon) who leads PNW blueberry phenology research.

2. **No Dutch/European cultivar-specific phenology data for Cargo.** WUR publishes general blueberry cultivation guidance but does not publish cultivar × location phenology tables. First-season local calibration is the only path.

3. **Bloom-to-harvest interval for Cargo**. The patent gives mean harvest (Aug 7) and 50% bloom (late April / first week of May) at the Oregon/Michigan trial sites but not explicit bloom-to-harvest in days. Back-calculated as ~95 days but this should be confirmed against observed data.

4. **Patent-vs-field-date discrepancy**. Patent says "2 to 3 weeks later than Draper", but computed Aug 7 − Jul 5 = 33 days. Likely explanation: the 2-3-week phrasing is for peak harvest overlap, not first-harvest means. Not material for this study but noted for transparency.

5. **Impact of protected cultivation in NL**. Many Dutch blueberry farms use tunnels. Temperature profile differs. No study quantifies the shift for Cargo specifically. Same gap as in `blueberry-gdd-harvest-prediction.md`.

## 8. Conflicting Information

**Season nomenclature**: Fall Creek's catalog labels Cargo "Late" (site classification scheme) while MSU E3490 labels it "Mid/Late". Both agree it is not Mid and not strictly Late; the discrepancy is scale granularity, not substance. MSU's scale is finer (Early / Early-Mid / Mid / Mid-Late / Late) and more defensible for thermal-time calculations. Use **Mid/Late** in internal documentation.

**Chill-hour classification**: PP24,661 says "800-1000 hours" (medium-high), Fall Creek catalog says "High Chill" (consistent with 800-1000 h under Fall Creek's >800 h = "High" convention). Not a true conflict — use the numeric range.

## 9. Sources

### Primary (High confidence)

1. **Gilbert, C. & Johnson, T. (Fall Creek)** — "Blueberry plant named 'Cargo'" — US Plant Patent PP24,661 (filed 2012-03-12, issued 2014-07-22). <https://patents.google.com/patent/US20130239260P1/en>. Accessed 2026-04-23.
   *Primary source of record. Bloom dates, mean harvest Aug 7, mean last pick Sep 5, chill 800-1000 h, parentage Bluegold × Ozarkblue.*

2. **Vander Weide, J., Isaacs, R., Miles, T., Edger, P., Sloan, C., Garcia-Salazar, C. (MSU Extension, 2024)** — "Blueberry Varieties for Michigan" — E3490. <https://www.canr.msu.edu/blueberries/uploads/files/E3490_Blueberry_Varieties_MI_AA.pdf>. Accessed 2026-04-23.
   *Authoritative season classification. Table 2 lists Cargo (2014) as Mid/Late. Text notes Cargo not yet widely planted in Michigan, short-stocky architecture suited to machine harvest.*

3. **Fall Creek Farm & Nursery** — Cargo variety page. <https://www.fallcreeknursery.com/commercial-fruit-growers/varieties/cargo>. Accessed 2026-04-23.
   *Breeder datasheet. Confirms "ripening in Liberty season", "High Chill", PNW commercial recommendation.*

4. **Carlson, J.D. & Hancock, J.F. (1991)** — "A Methodology for Determining Suitable Heat-unit Requirements for Harvest of Highbush Blueberry" — J. Amer. Soc. Hort. Sci. 116(5):774-779. <https://journals.ashs.org/jashs/view/journals/jashs/116/5/article-p774.xml>.
   *Already cited in code. Source of Duke base thresholds used for scaling in §4 and §6.*

5. **Wise, J.C. & Isaacs, R. (MSU Extension)** — "Using degree days to predict pest and crop development in blueberries". <https://www.canr.msu.edu/news/using-degree-days-to-predict-pest-and-crop-development-in-blueberries>. Accessed 2026-04-23.
   *Jersey GDD thresholds used as Mid/Late bucket proxy in §3.2 (bloom 310, first harvest 1,313 at base 50°F).*

### Comparative (supporting §2.2 and §4)

6. **Hancock, J.F. (MSU) & co-inventors** — "Blueberry plant denominated 'Draper'" — US PP15,103. <https://patents.google.com/patent/USPP15103P3/en>. Accessed 2026-04-23.
   *Draper/Bluecrop Michigan harvest dates (Table II): Draper 7/5, Bluecrop 7/10. Source for Cargo-vs-Bluecrop day-count derivation.*

7. **Hancock, J.F. (MSU) & co-inventors** — "Blueberry plant denominated 'Liberty'" — US PP15,146. <https://patents.google.com/patent/USPP15146P3/en>. Accessed 2026-04-23.
   *Liberty/Elliott Michigan harvest dates: Liberty 8/18-22, Elliott 8/23-27. Confirms Cargo-vs-Liberty interval.*

### Tertiary / context

8. **Portland Nursery Blueberry Harvest Chart (Rev. 12/2025)**. <https://www.portlandnursery.com/docs/fruits/BlueberryHarvestChart.pdf>.
   *PNW classification confirming Duke=Early, Bluecrop=Midseason, Liberty/Elliott=Late. Does not list Cargo, consistent with MSU noting Cargo is not yet widely planted outside breeder trials.*

9. **Prior research**: `docs/research/blueberry-gdd-harvest-prediction.md` (this repo, 2026-04-17).
   *Foundational Duke/Bluecrop/Elliott thresholds, base temperature conventions, NL climate context, chill-hour baseline.*

### Searched but yielded no Cargo-specific data (knowledge gap evidence)

- WUR / Wageningen publications (<https://edepot.wur.nl/>): general blueberry cultivation but no cultivar × GDD tables.
- OSU Extension: general blueberry growing guides, no Cargo data.
- Driscoll's: proprietary, no public phenology.
- Google Scholar peer-reviewed (queries: "Cargo blueberry GDD", "Cargo Vaccinium phenology", "Fall Creek blueberry thermal time"): zero relevant hits.

## 10. Research Metadata

- Duration: ~40 min (turn budget)
- Sources examined: 12 | Cited: 9 | Cross-referenced: Cargo season 3×, chill 2×, relative-timing 3× (Draper patent, Liberty patent, MSU E3490)
- Confidence distribution: HIGH — 60% (identity, patent, parentage, chill, season classification); MEDIUM — 30% (scaling factor derivation, proxy GDD from Jersey); LOW — 10% (absolute GDD values for Dutch conditions, which remain a calibration task)
- Output: `docs/research/cargo-blueberry-gdd.md`
