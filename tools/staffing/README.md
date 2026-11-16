# Five-week staffing study

Scope fixed by the requested methodology: DS 8889 / 9107; corporate weeks
910–914, 12 October–15 November 2026. This is a standalone read-only study,
not a change to dashboard roster denominators or Matryoshka notifications.

## Export on the VPS

```
cd /opt/courier-analytics/dashboard-code
python3 tools/probe_superset_vpn.py --check-login --collect-staffing
```

Uses existing private Superset credentials and temporary corporate VPN. This
explicit export mode permits up to 600 seconds for VPN use; other probe modes
retain their 120-second limit. No additional timer or Telegram sending is enabled.
It verifies that a "Время по заказам" chart uses dataset 3035, checks required
fields, pages each shop separately and compares before/after source row counts.
Identical page boundaries or incomplete counts stop the export.

Export: `/opt/courier-analytics/private/staffing-orders-910-914.json.gz`.
Source names and order rows remain private; never commit the export.

## Calculate and render

On the VPS use its existing Playwright environment:

```
/opt/courier-analytics/onec-venv/bin/python tools/run_staffing_report.py
```

Alternatively run locally with `--input PATH --output DIRECTORY` and Playwright
Chromium, or `--svg-only` for vector artifacts without a browser. The script requires Matplotlib and writes three 3200×2000 PNGs and SVGs,
a separate 3200×1620 core-trend chart, and `calculation.json`.
The current presentation includes only the 60% attendance scenario; the
former bad-weather panel is replaced with observed core trends.
No output is a real report until a complete source export has been loaded.

## Explicit interpretation and limits

- Workload: unique `id_order`, all statuses, delivery reporting date `date_supply`.
- Workforce: successful courier-service orders only; mobile types 6,9,15,16
  and type names containing `мобильн` excluded. Orders with unknown mobility
  status are excluded from individual metrics and explicitly reported.
- Courier identity: normalized name, per shop-week, as requested. Namesakes may merge.
- Export dates are formatted at source as wall-clock strings, interpreted as
  Moscow. Superset may re-encode the main temporal column as epoch milliseconds;
  decode to its original wall-clock value without adding a second Moscow offset.
- Attendance and whole delivery intervals use the start day/week, including
  overnight intervals. Gaps <=60 minutes count; larger gaps count zero;
  overlapping intervals are never added twice.
- A valid offline closing date takes precedence. Invalid ends and unverified
  intervals >12h are excluded from hours. Orders and attendance remain when
  their start is valid. These cases make the report provisional until reviewed;
  exceptions are counted explicitly.
- The 70/30 target describes actual shifts, not weekly headcount; weekly group
  headcount cannot be inferred from that target without group attendance assumptions.
- Comparative percentages use sums of shop-courier-weeks and group shifts, not
  averages of percentages or unique people over the entire five-week period.
- Historical source corrections can change records while paginating. Conflicting
  order versions stop analysis rather than silently selecting one.
- Pagination row totals check truncation, but cannot establish that the upstream
  mart itself contains every historical order; the retained source definition and
  order dates should also be reviewed when source data is received.
