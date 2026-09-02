# Changelog

A monthly summary of new functionality delivered across the WP6 digital twins
(blue, red and grey). Each entry links to that month's full changelog, with
deep links into the live dashboards.

| Month | Highlights |
|-------|------------|
| [July / August 2026](2026-09.html) | **Production moved to the new cluster** &mdash; both twins evacuated off the old Kubernetes cluster on 15 July, databases dumped, restored and verified (Blue's 5.34&nbsp;M readings plus the irreplaceable yearly manual data), production URLs flipped, old cluster kept as a one-step rollback &mdash; and six storage-related faults found and fixed along the way. **Source-aware sync health** &mdash; the Sync Status page now separates *our pipeline is failing* from *the upstream source has gone quiet*, with a 7-day reliability score, failing-since and a per-run sparkline. **End-to-end tracing** &mdash; every request and scheduled job emits OpenTelemetry traces, with logs stamped by trace ID. Plus second &amp; third harvest thresholds on Blue's GDD tracker, and fixes for a login-provider outage that crash-looped the dashboards and 23 days of silently failing nightly exports &mdash; and a community fix making the twins render correctly on non-UTF-8 Windows systems. |
| [June / July 2026](2026-07.html) | **Soil-condition forecasting for Blue** — a 7-day look-ahead on soil moisture &amp; temperature per treatment, retrained on every deploy. **Manual data in context** — fertigation events overlaid on soil charts, a manual-measurement monitor, and mixed sensor/manual views. **GDD on OpenMeteo modeled weather** — a full calendar year (from Jan 2024) now analysable, with growth constants set to recognised values. **Blue fully operational on the SPoHF Datalake** — the direct Yookr API fallback retired, removing ~686 lines of code and 4.1 M duplicate rows (43.5% of the readings table). Plus per-axis chart types (line/scatter/boxplot) and a templates/asset refactor. |
| [May / June 2026](2026-05.html) | **Manual data sources for Blue** — insect-trap CSV and yearly `long_data` measurements on a new shared, twin-agnostic upload capability. **Multi-height sensor views for Red** — a Multi Height section mapping PAR & DLI across sensor heights. Plus server-side chart aggregation, min/max range bands, and coverage-by-source status pages. |

<!-- Add a new row per month, newest first, linking to docs/changelog/<YYYY-MM>.html -->
