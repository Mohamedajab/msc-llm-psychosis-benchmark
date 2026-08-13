"""Build a dependency-free static HTML meeting snapshot from demo outputs."""

# The executable-path bootstrap must precede local imports; long lines inside
# the emitted HTML/CSS are intentional and do not affect Python readability.
# ruff: noqa: E402, E501

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import statistics
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_demo import DEFAULT_OUTPUT_ROOT, DEMO_BANNER, generate_demo

DEFAULT_SNAPSHOT = ROOT / "outputs" / "static_snapshot.html"


def _atomic_write_text(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _read_demo(demo_root: Path) -> tuple[dict[str, Any], list[dict[str, str]], list[Any]]:
    required = (
        demo_root / "manifest.json",
        demo_root / "trajectory_annotations.csv",
        demo_root / "conversations.json",
    )
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Missing demo outputs: " + ", ".join(missing) + ". Run scripts/generate_demo.py first."
        )
    manifest = json.loads(required[0].read_text(encoding="utf-8"))
    with required[1].open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    conversations = json.loads(required[2].read_text(encoding="utf-8"))
    if manifest.get("data_status") != "demo_fixture":
        raise ValueError("Static meeting snapshot accepts demo_fixture inputs only")
    return manifest, rows, conversations


def _table(headers: list[str], rows: list[list[object]]) -> str:
    header_html = "".join(f"<th>{html.escape(value)}</th>" for value in headers)
    row_html = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(str(value))}</td>" for value in row)
        row_html.append(f"<tr>{cells}</tr>")
    return (
        '<div class="table-wrap"><table><thead><tr>'
        + header_html
        + "</tr></thead><tbody>"
        + "".join(row_html)
        + "</tbody></table></div>"
    )


def _axis_svg(rows: list[dict[str, str]], axis: str) -> str:
    """Render an inline accessible 0-2 trajectory without JavaScript."""

    grouped: dict[tuple[str, int], list[int]] = defaultdict(list)
    for row in rows:
        grouped[(row["fixture_profile"], int(row["turn_number"]))].append(int(row[axis]))
    width, height = 720, 245
    left, right, top, bottom = 55, 20, 25, 45
    plot_width = width - left - right
    plot_height = height - top - bottom

    def x(turn: int) -> float:
        return left + ((turn - 1) / 5) * plot_width

    def y(value: float) -> float:
        return top + ((2 - value) / 2) * plot_height

    elements = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{html.escape(axis)} score by turn for the two demo fixture profiles">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]
    for score in (0, 1, 2):
        line_y = y(score)
        elements.append(
            f'<line x1="{left}" y1="{line_y:.1f}" x2="{width - right}" '
            f'y2="{line_y:.1f}" stroke="#d6dce5" stroke-width="1"/>'
        )
        elements.append(
            f'<text x="{left - 15}" y="{line_y + 5:.1f}" text-anchor="end" '
            f'font-size="12" fill="#334155">{score}</text>'
        )
    for turn in range(1, 7):
        elements.append(
            f'<text x="{x(turn):.1f}" y="{height - 17}" text-anchor="middle" '
            f'font-size="12" fill="#334155">{turn}</text>'
        )
    colours = {"safe": "#2563a6", "risk_prone": "#c46d10"}
    labels = {"safe": "Safer fixture", "risk_prone": "Risk-prone fixture"}
    for profile in ("safe", "risk_prone"):
        values = [statistics.fmean(grouped[(profile, turn)]) for turn in range(1, 7)]
        points = " ".join(
            f"{x(turn):.1f},{y(value):.1f}" for turn, value in enumerate(values, start=1)
        )
        colour = colours[profile]
        elements.append(
            f'<polyline points="{points}" fill="none" stroke="{colour}" '
            'stroke-width="3" stroke-linejoin="round"/>'
        )
        for turn, value in enumerate(values, start=1):
            elements.append(
                f'<circle cx="{x(turn):.1f}" cy="{y(value):.1f}" r="4" fill="{colour}"/>'
            )
        legend_x = left + (250 if profile == "risk_prone" else 0)
        elements.append(
            f'<line x1="{legend_x}" y1="12" x2="{legend_x + 25}" y2="12" '
            f'stroke="{colour}" stroke-width="3"/>'
        )
        elements.append(
            f'<text x="{legend_x + 32}" y="16" font-size="12" '
            f'fill="#0f172a">{labels[profile]}</text>'
        )
    elements.append(
        f'<text x="15" y="{top + plot_height / 2:.1f}" transform="rotate(-90 15 '
        f'{top + plot_height / 2:.1f})" text-anchor="middle" font-size="12" '
        'fill="#334155">Ordinal score (0-2)</text>'
    )
    elements.append(
        f'<text x="{left + plot_width / 2:.1f}" y="{height - 2}" text-anchor="middle" '
        'font-size="12" fill="#334155">Turn</text></svg>'
    )
    return "".join(elements)


def _mean_summary(rows: list[dict[str, str]]) -> list[list[object]]:
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[(row["fixture_profile"], row["context_condition"])].append(row)
    summary: list[list[object]] = []
    for (profile, condition), values in sorted(groups.items()):
        summary.append(
            [
                profile.replace("_", " ").title(),
                condition,
                len(values),
                f"{statistics.fmean(int(value['A1']) for value in values):.2f}",
                f"{statistics.fmean(int(value['A2']) for value in values):.2f}",
                f"{statistics.fmean(int(value['A3']) for value in values):.2f}",
            ]
        )
    return summary


def generate_snapshot(
    demo_root: str | Path = DEFAULT_OUTPUT_ROOT,
    output: str | Path = DEFAULT_SNAPSHOT,
) -> Path:
    """Create the deterministic self-contained HTML snapshot."""

    source = Path(demo_root)
    manifest, trajectory_rows, conversations = _read_demo(source)
    if len(conversations) != 4 or len(trajectory_rows) != 24:
        raise ValueError("Expected the complete 4-conversation / 24-response demo fixture")

    run_table = _table(
        ["Order", "Fixture profile", "Context condition", "Turns"],
        [
            [
                index,
                run["fixture_profile"].replace("_", " ").title(),
                run["context_condition"],
                run["turn_count"],
            ]
            for index, run in enumerate(manifest["runs"], start=1)
        ],
    )
    summary_table = _table(
        ["Fixture profile", "Context condition", "Responses", "Mean A1", "Mean A2", "Mean A3"],
        _mean_summary(trajectory_rows),
    )

    examples = []
    for profile in ("safe", "risk_prone"):
        record = next(
            item
            for item in conversations
            if item["header"]["model_slot"] == f"fixture_{profile}"
            and item["header"]["context_condition"] == "no_preloaded_context"
        )
        turn = record["turns"][-1]
        label = "Safer fixture" if profile == "safe" else "Risk-prone fixture"
        examples.append(
            '<article class="example"><h3>'
            + html.escape(label)
            + " — turn 6</h3><p><strong>Synthetic user:</strong> "
            + html.escape(turn["user_message"])
            + "</p><p><strong>Fixture response:</strong> "
            + html.escape(turn["result"]["text"])
            + "</p></article>"
        )

    limitations = "".join(f"<li>{html.escape(value)}</li>" for value in manifest["limitations"])
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Controlled Multi-Turn Benchmark — Demo Snapshot</title>
<style>
:root {{ color-scheme: light; --ink:#162033; --muted:#526176; --line:#d7dee8; --panel:#f6f8fb; --accent:#184f82; --warning:#7a3e00; }}
* {{ box-sizing:border-box; }} body {{ margin:0; background:#eef2f6; color:var(--ink); font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ width:min(1080px,calc(100% - 32px)); margin:32px auto; background:white; padding:40px; border:1px solid var(--line); box-shadow:0 8px 30px rgba(15,23,42,.07); }}
h1 {{ font-size:2rem; line-height:1.2; margin:.15rem 0 .5rem; }} h2 {{ margin-top:2.2rem; border-bottom:1px solid var(--line); padding-bottom:.35rem; }}
.eyebrow {{ color:var(--accent); font-size:.82rem; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }}
.banner {{ margin:24px 0; padding:14px 16px; border:2px solid #d17a1f; background:#fff8ed; color:var(--warning); font-weight:800; }}
.metrics {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }} .metric {{ background:var(--panel); border:1px solid var(--line); padding:16px; }}
.metric strong {{ display:block; font-size:1.65rem; }} .metric span,.note {{ color:var(--muted); font-size:.9rem; }}
.table-wrap {{ overflow-x:auto; }} table {{ width:100%; border-collapse:collapse; }} th,td {{ text-align:left; border-bottom:1px solid var(--line); padding:9px 10px; }} th {{ background:var(--panel); }}
.charts {{ display:grid; grid-template-columns:1fr; gap:18px; }} .chart {{ border:1px solid var(--line); padding:14px; }} .chart h3 {{ margin:0 0 8px; }}
.examples {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }} .example {{ background:var(--panel); border-left:4px solid var(--accent); padding:14px; }}
code {{ word-break:break-all; }} footer {{ margin-top:36px; border-top:1px solid var(--line); padding-top:16px; color:var(--muted); font-size:.86rem; }}
@media(max-width:760px) {{ main {{ padding:22px; }} .metrics,.examples {{ grid-template-columns:1fr; }} }}
@media print {{ body {{ background:white; }} main {{ margin:0; width:100%; border:0; box-shadow:none; }} }}
</style>
</head>
<body><main>
<div class="eyebrow">Loughborough University · MSc Advanced Computer Science</div>
<h1>A Controlled Multi-Turn Benchmark for Belief Reinforcement</h1>
<p>Static local meeting snapshot of the implemented research workflow.</p>
<div class="banner">{html.escape(DEMO_BANNER)}</div>
<section class="metrics">
<div class="metric"><strong>{manifest["conversation_count"]}</strong><span>synthetic conversations</span></div>
<div class="metric"><strong>{manifest["response_count"]}</strong><span>fixture responses</span></div>
<div class="metric"><strong>{manifest["annotation_count"]}</strong><span>seven-axis annotations</span></div>
<div class="metric"><strong>0</strong><span>network calls</span></div>
</section>
<h2>Fixture design</h2>
<p>One frozen six-turn fixed-belief script is crossed with two deterministic response profiles and both context conditions. This exercises the runner, exact history growth, storage, blinded annotation preparation and trajectory analysis offline.</p>
{run_table}
<h2>Separate primary outcomes</h2>
<p>A1 (Delusion Confirmation), A2 (Harm Enablement) and A3 (Safety Intervention) remain separate ordinal outcomes. No combined seven-axis score is produced.</p>
{summary_table}
<div class="charts">
<div class="chart"><h3>A1 — Delusion Confirmation</h3>{_axis_svg(trajectory_rows, "A1")}</div>
<div class="chart"><h3>A2 — Harm Enablement</h3>{_axis_svg(trajectory_rows, "A2")}</div>
<div class="chart"><h3>A3 — Safety Intervention</h3>{_axis_svg(trajectory_rows, "A3")}</div>
</div>
<h2>Transcript contrast</h2>
<div class="examples">{"".join(examples)}</div>
<h2>Reproducibility</h2>
<p><strong>Fixture version:</strong> {html.escape(manifest["fixture_version"])}<br>
<strong>Frozen script:</strong> {html.escape(manifest["script_id"])}<br>
<strong>Configuration hash:</strong> <code>{html.escape(manifest["configuration_hash"])}</code><br>
<strong>Network called:</strong> false</p>
<h2>Limitations</h2><ul>{limitations}</ul>
<footer>This file was generated entirely from saved <code>data/demo</code> outputs. It contains no live-provider result and makes no clinical claim.</footer>
</main></body></html>
"""
    return _atomic_write_text(Path(output), document)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a self-contained static HTML snapshot from demo data."
    )
    parser.add_argument("--demo-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument(
        "--regenerate-demo",
        action="store_true",
        help="Regenerate deterministic demo files before building the snapshot",
    )
    arguments = parser.parse_args(argv)
    try:
        if arguments.regenerate_demo:
            generate_demo(arguments.demo_root)
        result = generate_snapshot(arguments.demo_root, arguments.output)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(DEMO_BANNER)
    print(result.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
