"""Render the accumulated eval JSONL history into one self-contained HTML report.

The harness appends every run to a JSONL file (see ``evals/results.py``); this
module turns that history into a single static HTML page — an overall summary, a
per-model leaderboard ranked by pass rate, and a full detail table. No external
assets (CSS is inlined), so the file opens anywhere.

Pure rendering — :func:`load_records`, :func:`summarize`, and :func:`render_html`
are deterministic functions of the record list, so they're easy to test.

    uv run python -m evals.report_html --in runs.jsonl --out report.html
"""

from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path

# Detail strings can be long (a pytest traceback tail); keep the table readable.
_DETAIL_MAX = 100


def load_records(path: Path) -> list[dict]:
    """Read a JSONL run file into a list of record dicts, skipping blank lines."""
    records = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def summarize(records: list[dict]) -> dict:
    """Roll records up into overall totals and a per-model breakdown.

    The per-model list is sorted best-pass-rate-first (ties broken by name), so it
    doubles as a leaderboard. A "run" is a distinct (timestamp, model) pair.
    """
    by: dict[str, dict] = {}
    for r in records:
        model = r.get("model") or "—"
        d = by.setdefault(
            model,
            {
                "model": model,
                "total": 0,
                "passed": 0,
                "total_tokens": 0,
                "tool_calls": 0,
                "tool_errors": 0,
                "tool_unknown": 0,
                "duration_s": 0.0,
            },
        )
        d["total"] += 1
        d["passed"] += 1 if r.get("passed") else 0
        d["total_tokens"] += r.get("total_tokens") or 0
        d["tool_calls"] += r.get("tool_calls") or 0
        d["tool_errors"] += r.get("tool_errors") or 0
        d["tool_unknown"] += r.get("tool_unknown") or 0
        d["duration_s"] += r.get("duration_s") or 0.0
    for d in by.values():
        d["pass_rate"] = d["passed"] / d["total"] if d["total"] else 0.0

    total = len(records)
    passed = sum(1 for r in records if r.get("passed"))
    return {
        "total": total,
        "passed": passed,
        "pass_rate": passed / total if total else 0.0,
        "total_tokens": sum(r.get("total_tokens") or 0 for r in records),
        "runs": len({(r.get("timestamp"), r.get("model")) for r in records}),
        "by_model": sorted(by.values(), key=lambda d: (-d["pass_rate"], d["model"])),
    }


# Line colours for the per-model trend lines (cycled).
_PALETTE = ["#46d68a", "#5b9cff", "#f7b955", "#ff6b6b", "#b98cff", "#3fd0c9", "#ff9f43"]


def _runs_over_time(records: list[dict]) -> dict[str, list[dict]]:
    """Aggregate records into per-model *runs* (a distinct timestamp), sorted in time.

    Each run carries its ``pass_rate`` and total ``tokens`` — the series a trend
    chart plots. ``{model: [{timestamp, pass_rate, passed, total, tokens}, ...]}``.
    """
    by_run: dict[tuple[str, str], dict] = {}
    for r in records:
        key = (r.get("model") or "—", str(r.get("timestamp") or ""))
        d = by_run.setdefault(key, {"passed": 0, "total": 0, "tokens": 0})
        d["total"] += 1
        d["passed"] += 1 if r.get("passed") else 0
        d["tokens"] += r.get("total_tokens") or 0

    by_model: dict[str, list[dict]] = {}
    for (model, ts), d in by_run.items():
        by_model.setdefault(model, []).append(
            {
                "timestamp": ts,
                "pass_rate": d["passed"] / d["total"] if d["total"] else 0.0,
                "passed": d["passed"],
                "total": d["total"],
                "tokens": d["tokens"],
            }
        )
    for runs in by_model.values():
        runs.sort(key=lambda run: run["timestamp"])
    return by_model


def _svg_line_chart(by_model, value_of, *, title, y_max, fmt, width=720, height=240):
    """Render a self-contained inline-SVG line chart, one line per model.

    ``value_of(run) -> float`` selects the y value; the x axis is shared time (the
    sorted set of all run timestamps). Pure string building — no JS, no external
    assets — so it embeds directly in the report and is trivially testable.
    """
    all_ts = sorted({run["timestamp"] for runs in by_model.values() for run in runs})
    if not all_ts or y_max <= 0:
        return ""
    pad_l, pad_r, pad_t, pad_b = 48, 12, 28, 22
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b

    def x(ts: str) -> float:
        if len(all_ts) == 1:
            return pad_l + plot_w / 2
        return pad_l + plot_w * all_ts.index(ts) / (len(all_ts) - 1)

    def y(v: float) -> float:
        return pad_t + plot_h * (1 - min(v, y_max) / y_max)

    parts = [
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{escape(title)}">'
        f'<text class="ctitle" x="{pad_l}" y="16">{escape(title)}</text>'
    ]
    # Horizontal gridlines + y labels at quarters.
    for i in range(5):
        v = y_max * i / 4
        gy = y(v)
        parts.append(
            f'<line class="grid" x1="{pad_l}" y1="{gy:.1f}" x2="{width - pad_r}" y2="{gy:.1f}"/>'
        )
        parts.append(f'<text class="ylab" x="{pad_l - 6}" y="{gy + 3:.1f}">{escape(fmt(v))}</text>')
    # One polyline (+ dots) per model.
    for i, model in enumerate(sorted(by_model)):
        color = _PALETTE[i % len(_PALETTE)]
        runs = by_model[model]
        pts = " ".join(f"{x(r['timestamp']):.1f},{y(value_of(r)):.1f}" for r in runs)
        parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{pts}"/>')
        for r in runs:
            cx, cy = x(r["timestamp"]), y(value_of(r))
            parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3" fill="{color}"/>')
    # Legend.
    lx = pad_l
    for i, model in enumerate(sorted(by_model)):
        color = _PALETTE[i % len(_PALETTE)]
        parts.append(f'<rect x="{lx}" y="{height - 12}" width="9" height="9" fill="{color}"/>')
        parts.append(f'<text class="leg" x="{lx + 13}" y="{height - 4}">{escape(model)}</text>')
        lx += 16 + len(model) * 7
    parts.append("</svg>")
    return "".join(parts)


def _trend_charts(records: list[dict]) -> str:
    """Pass-rate and token trend charts over time, or "" when there's no data."""
    by_model = _runs_over_time(records)
    if not by_model:
        return ""
    passrate = _svg_line_chart(
        by_model,
        lambda r: r["pass_rate"],
        title="Pass rate over time",
        y_max=1.0,
        fmt=lambda v: f"{v * 100:.0f}%",
    )
    max_tokens = max((r["tokens"] for runs in by_model.values() for r in runs), default=0)
    tokens = _svg_line_chart(
        by_model,
        lambda r: r["tokens"],
        title="Tokens per run over time",
        y_max=max_tokens or 1,
        fmt=lambda v: f"{v / 1000:.0f}k" if v >= 1000 else f"{v:.0f}",
    )
    return f'\n  <h2>Trends</h2>\n  <div class="charts">{passrate}{tokens}</div>'


def _card(label: str, value: str) -> str:
    return (
        f'<div class="card"><div class="num">{value}</div>'
        f'<div class="lbl">{escape(label)}</div></div>'
    )


def _bar(rate: float) -> str:
    pct = round(rate * 100)
    hue = round(rate * 120)  # 0=red, 120=green
    return (
        f'<div class="bar"><div class="fill" style="width:{pct}%;'
        f'background:hsl({hue},65%,45%)"></div><span>{pct}%</span></div>'
    )


def _model_rows(by_model: list[dict]) -> str:
    rows = []
    for m in by_model:
        rows.append(
            "<tr>"
            f"<td>{escape(m['model'])}</td>"
            f"<td>{_bar(m['pass_rate'])}</td>"
            f"<td class='r'>{m['passed']}/{m['total']}</td>"
            f"<td class='r'>{m['tool_calls']}</td>"
            f"<td class='r'>{m['tool_errors']}</td>"
            f"<td class='r'>{m['tool_unknown']}</td>"
            f"<td class='r'>{m['total_tokens']:,}</td>"
            f"<td class='r'>{m['duration_s']:.1f}s</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _detail_rows(records: list[dict]) -> str:
    rows = []
    # Newest first, so a fresh run is at the top.
    for r in sorted(records, key=lambda r: str(r.get("timestamp")), reverse=True):
        passed = bool(r.get("passed"))
        badge = "PASS" if passed else "FAIL"
        cls = "pass" if passed else "fail"
        detail = (r.get("detail") or "").splitlines()
        detail = detail[0] if detail else ""
        if len(detail) > _DETAIL_MAX:
            detail = detail[:_DETAIL_MAX] + "…"
        rows.append(
            "<tr>"
            f"<td class='dim'>{escape(str(r.get('timestamp') or ''))}</td>"
            f"<td>{escape(str(r.get('model') or '—'))}</td>"
            f"<td>{escape(str(r.get('task_id') or ''))}</td>"
            f"<td><span class='badge {cls}'>{badge}</span></td>"
            f"<td class='r'>{r.get('iterations') or 0}</td>"
            f"<td class='r'>{r.get('tool_calls') or 0}</td>"
            f"<td class='r'>{r.get('tool_errors') or 0}</td>"
            f"<td class='r'>{r.get('tool_unknown') or 0}</td>"
            f"<td class='r'>{(r.get('total_tokens') or 0):,}</td>"
            f"<td class='r'>{(r.get('duration_s') or 0.0):.1f}s</td>"
            f"<td class='dim'>{escape(detail)}</td>"
            "</tr>"
        )
    return "\n".join(rows)


_CSS = """
:root { color-scheme: light dark; }
body { font: 14px/1.5 -apple-system, system-ui, sans-serif; margin: 0; padding: 2rem;
       background: #0f1115; color: #e6e6e6; }
h1 { margin: 0 0 .25rem; font-size: 1.5rem; }
.sub { color: #8a93a2; margin-bottom: 1.5rem; }
.cards { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 2rem; }
.card { background: #1a1d24; border: 1px solid #2a2f3a; border-radius: 10px;
        padding: 1rem 1.25rem; min-width: 120px; }
.card .num { font-size: 1.6rem; font-weight: 600; }
.card .lbl { color: #8a93a2; font-size: .8rem; text-transform: uppercase; letter-spacing: .04em; }
h2 { font-size: 1.1rem; margin: 2rem 0 .75rem; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: .5rem .6rem; border-bottom: 1px solid #2a2f3a; }
th { color: #8a93a2; font-weight: 600; text-transform: uppercase;
     font-size: .72rem; letter-spacing: .04em; }
td.r, th.r { text-align: right; font-variant-numeric: tabular-nums; }
td.dim { color: #8a93a2; }
tr:hover td { background: #161922; }
.badge { padding: .1rem .5rem; border-radius: 5px; font-weight: 700; font-size: .72rem; }
.badge.pass { background: #143d2a; color: #46d68a; }
.badge.fail { background: #3d1717; color: #ff6b6b; }
.bar { position: relative; background: #2a2f3a; border-radius: 5px;
       height: 18px; width: 160px; overflow: hidden; }
.bar .fill { height: 100%; }
.bar span { position: absolute; inset: 0; text-align: center;
            font-size: .72rem; line-height: 18px; }
.charts { display: flex; gap: 1rem; flex-wrap: wrap; }
.chart { background: #1a1d24; border: 1px solid #2a2f3a; border-radius: 10px;
         padding: .5rem; flex: 1 1 340px; max-width: 100%; }
.chart .ctitle { fill: #e6e6e6; font-size: 13px; font-weight: 600; }
.chart .grid { stroke: #2a2f3a; stroke-width: 1; }
.chart .ylab, .chart .leg { fill: #8a93a2; font-size: 10px; }
.chart .ylab { text-anchor: end; }
"""


def render_html(records: list[dict], *, title: str = "Eval Results", generated_at: str = "") -> str:
    """Render records into a complete, self-contained HTML document (pure)."""
    s = summarize(records)
    rate_pct = round(s["pass_rate"] * 100)
    cards = "".join(
        [
            _card("Pass rate", f"{rate_pct}%"),
            _card("Passed", f"{s['passed']}/{s['total']}"),
            _card("Runs", str(s["runs"])),
            _card("Models", str(len(s["by_model"]))),
            _card("Tokens", f"{s['total_tokens']:,}"),
        ]
    )
    sub = escape(generated_at) if generated_at else f"{s['total']} results"

    charts = _trend_charts(records)

    model_section = ""
    if s["by_model"]:
        model_section = f"""
  <h2>Models</h2>
  <table>
    <thead><tr><th>Model</th><th>Pass rate</th><th class='r'>Passed</th>
      <th class='r'>Calls</th><th class='r'>Errors</th><th class='r'>Unknown</th>
      <th class='r'>Tokens</th><th class='r'>Time</th></tr></thead>
    <tbody>
{_model_rows(s["by_model"])}
    </tbody>
  </table>"""

    detail_section = ""
    if records:
        detail_section = f"""
  <h2>All results</h2>
  <table>
    <thead><tr><th>When</th><th>Model</th><th>Task</th><th>Result</th>
      <th class='r'>Iter</th><th class='r'>Calls</th><th class='r'>Err</th>
      <th class='r'>Unk</th><th class='r'>Tokens</th><th class='r'>Time</th>
      <th>Detail</th></tr></thead>
    <tbody>
{_detail_rows(records)}
    </tbody>
  </table>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>{_CSS}</style>
</head>
<body>
  <h1>{escape(title)}</h1>
  <div class="sub">{sub}</div>
  <div class="cards">{cards}</div>{charts}{model_section}{detail_section}
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render eval JSONL history into an HTML report.")
    parser.add_argument("--in", dest="in_path", required=True, help="input runs JSONL file")
    parser.add_argument("--out", required=True, help="output HTML file")
    parser.add_argument("--title", default="Eval Results", help="report title")
    args = parser.parse_args(argv)

    records = load_records(args.in_path)
    html = render_html(records, title=args.title)
    Path(args.out).write_text(html)
    print(f"Wrote {args.out} ({len(records)} results)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
