"""Building blocks of the Home landing page (haunted-design, REQ-HD-09 to REQ-HD-11).

Pure module: no Streamlit. It reads three committed files and nothing else, never the network:

- ``data/benchmark/results.json``: precision and recall of Zombie Subscriptions and of Phantom
  Invoices, copied from the ``totals`` block of each app (nothing is recomputed);
- ``data/samples/phantom_demo/facturae/``: the sample invoices that the reviewer validated once
  against the official Facturae XSD (25 of 25, DN-RF-23). The check is not part of CI, so the
  card says so, and it prints the number of files now in the folder next to the 25 checked;
- ``data/public/ine_cpi_ipc290751.json``: the INE consumer price index snapshot.

A file that is missing or malformed gives ``n/a`` for its fact and never an exception. The number
of tests is not shown anywhere: it changes with every session.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path

from ledger_kit.public_data import DEFAULT_SNAPSHOT_PATH, SnapshotError, load_snapshot
from ledger_kit.ui.icons import icon
from ledger_kit.ui.theme import PHANTOM, VAMPIRE, ZOMBIE, Accent, card_html

ROOT = Path(__file__).resolve().parents[2]
RESULTS_PATH: Path = ROOT / "data" / "benchmark" / "results.json"
FACTURAE_DIR: Path = ROOT / "data" / "samples" / "phantom_demo" / "facturae"

RESULTS_SOURCE = "data/benchmark/results.json"
FACTURAE_SOURCE = "data/samples/phantom_demo/facturae/"
CPI_SOURCE = "data/public/ine_cpi_ipc290751.json"

# The reviewer validated this many sample files against the official XSD (session 8e, DN-RF-23).
XSD_CHECKED_FILES: int = 25
NOT_AVAILABLE = "n/a"

# The apps of the benchmark, in the order of the results file page.
BENCHMARK_APPS: tuple[tuple[str, str], ...] = (
    ("zombie", "Zombie Subscriptions"),
    ("phantom", "Phantom Invoices"),
)


@dataclass(frozen=True)
class Fact:
    """One card of the proof strip: label, large figure, a note and the file it comes from."""

    label: str
    figure: str
    note: str
    source: str


@dataclass(frozen=True)
class Tile:
    """One app tile: the app's accent (name and icon), a one-line purpose and its demo numbers."""

    accent: Accent
    purpose: str
    stats: tuple[tuple[str, str], ...]  # (figure, label) of the demo statement


# Demo numbers of the committed demo data. tests/test_ui_pages.py runs the three apps on their
# demo data and compares, so a change in a detector cannot leave a stale number on Home.
TILES: tuple[Tile, ...] = (
    Tile(
        ZOMBIE,
        "Forgotten recurring charges on a personal bank statement.",
        (("3", "tombstones"), ("19", "alerts")),
    ),
    Tile(
        PHANTOM,
        "Duplicate invoices, IBAN changes and VAT errors in a small business.",
        (("3", "critical"), ("6", "warnings")),
    ),
    Tile(
        VAMPIRE,
        "The bank fees that drain an account, and what they cost a year.",
        (("3", "coffins"), ("6", "alerts")),
    ),
)

# The three layers of the diagram: (step, first line, second line).
DIAGRAM_STEPS: tuple[tuple[str, str, str], ...] = (
    ("1 · Ingestion", "files in, rows cited", "bad rows quarantined"),
    ("2 · Detectors", "plain Python rules", "each alert cites rows"),
    ("3 · Explainer", "LLM words the alert", "number guard checks it"),
)
DIAGRAM_TITLE = (
    "How a figure reaches the screen: ingestion, deterministic detectors, then the explainer "
    "with the number guard"
)


def _read_json(path: Path) -> dict | None:
    """Return the JSON object in a file; None when it is missing, unreadable or not an object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _text(value: object) -> str:
    """Return a ratio of the results file as text; null in the file is shown as n/a."""
    return NOT_AVAILABLE if value is None else str(value)


def benchmark_facts(path: Path = RESULTS_PATH) -> list[Fact]:
    """Return the precision fact of each benchmarked app, copied from its ``totals`` block."""
    data = _read_json(path) or {}
    facts = []
    for key, title in BENCHMARK_APPS:
        label = f"Benchmark precision · {title}"
        try:
            totals = data["apps"][key]["totals"]
            precision, recall = _text(totals["precision"]), _text(totals["recall"])
            scenarios = int(data["scenarios_per_app"])
        except (KeyError, TypeError, ValueError):
            unusable = "The committed benchmark results are not usable."
            facts.append(Fact(label, NOT_AVAILABLE, unusable, RESULTS_SOURCE))
            continue
        note = f"Recall {recall} on {scenarios} synthetic scenarios."
        facts.append(Fact(label, precision, note, RESULTS_SOURCE))
    return facts


def facturae_fact(directory: Path = FACTURAE_DIR) -> Fact:
    """Return the XSD fact: files checked against the files in the folder, with its caveat."""
    label = "Facturae 3.2.2 samples"
    try:
        count = sum(1 for item in directory.iterdir() if item.suffix.lower() == ".xml")
    except OSError:
        count = 0
    if count == 0:
        return Fact(label, NOT_AVAILABLE, "The sample folder is not available.", FACTURAE_SOURCE)
    note = (
        "valid against the official XSD. Checked once by the reviewer with lxml; "
        "the check is not part of CI."
    )
    if count != XSD_CHECKED_FILES:
        note += f" The folder has {count} files now: validate again."
    return Fact(label, f"{XSD_CHECKED_FILES} of {count}", note, FACTURAE_SOURCE)


def cpi_fact(path: Path = DEFAULT_SNAPSHOT_PATH) -> Fact:
    """Return the public-data fact: the INE series code, its months and its licence."""
    label = "Public data · INE"
    try:
        series = load_snapshot(path)
    except SnapshotError:
        return Fact(label, NOT_AVAILABLE, "The committed CPI snapshot is not usable.", CPI_SOURCE)
    note = (
        f"Consumer price index, {series.first_month} to {series.last_month}, "
        f"licence {series.licence}. Committed, never downloaded at run time."
    )
    return Fact(label, series.series_code, note, CPI_SOURCE)


def proof_facts(
    results_path: Path = RESULTS_PATH,
    facturae_dir: Path = FACTURAE_DIR,
    cpi_path: Path = DEFAULT_SNAPSHOT_PATH,
) -> list[Fact]:
    """Return the four facts of the proof strip, each read from its committed file."""
    return [*benchmark_facts(results_path), facturae_fact(facturae_dir), cpi_fact(cpi_path)]


def proof_strip_html(facts: list[Fact]) -> str:
    """Return the grid of fact cards; every text is escaped by ``card_html``."""
    cards = "".join(card_html(f.label, f.figure, f.note, (f.source,)) for f in facts)
    return f'<div class="gl-grid gl-proof">{cards}</div>'


def tile_html(tile: Tile) -> str:
    """Return one app tile: icon and name in the app's accent, purpose, demo numbers."""
    stats = "".join(
        f'<div><div class="gl-figure">{html.escape(figure)}</div>'
        f'<div class="gl-label">{html.escape(label)}</div></div>'
        for figure, label in tile.stats
    )
    return (
        f'<div class="gl-card gl-tile gl-tile-{tile.accent.key}">'
        f'<div class="gl-tile-head">{icon(tile.accent.icon, size=38, decorative=True)}'
        f'<span class="gl-tile-name">{html.escape(tile.accent.title)}</span></div>'
        f'<div class="gl-note">{html.escape(tile.purpose)}</div>'
        f'<div class="gl-stats">{stats}</div></div>'
    )


def tiles_html(tiles: tuple[Tile, ...] = TILES) -> str:
    """Return the grid of the three app tiles."""
    return f'<div class="gl-grid gl-tiles">{"".join(tile_html(tile) for tile in tiles)}</div>'


def diagram_html() -> str:
    """Return the small inline SVG of the three layers; the guard's box wears the accent."""
    shapes = []
    for index, (step, first, second) in enumerate(DIAGRAM_STEPS):
        x = index * 260
        guard = ' class="gl-guard"' if index == len(DIAGRAM_STEPS) - 1 else ""
        centre = x + 110
        shapes.append(
            f'<rect x="{x}" y="20" width="220" height="110" rx="6"{guard}/>'
            f'<text x="{centre}" y="55" text-anchor="middle" font-size="15" '
            f'class="gl-diagram-step">{html.escape(step)}</text>'
            f'<text x="{centre}" y="86" text-anchor="middle" font-size="17">'
            f"{html.escape(first)}</text>"
            f'<text x="{centre}" y="110" text-anchor="middle" font-size="17">'
            f"{html.escape(second)}</text>"
        )
        if index < len(DIAGRAM_STEPS) - 1:
            shapes.append(f'<path d="M{x + 228} 75h24m-7-6 7 6-7 6"/>')
    return (
        '<div class="gl-diagram">'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 740 150" role="img">'
        f"<title>{html.escape(DIAGRAM_TITLE)}</title>{''.join(shapes)}</svg></div>"
    )
