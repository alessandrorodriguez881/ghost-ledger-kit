"""Tests of scripts/ledger_scan.py (spec scan-command, tasks SCAN1 to SCAN3).

The command is run in process through ``main(argv, out)``, and once as a real subprocess to prove
that it starts from any working directory. The expected alert ids come from each app's own
``run_pipeline`` on the committed demo files, as the pages call it (the zombie run with the empty
aliases and cancellation dates the command uses). All data is synthetic; no key, model or network.
"""

import hashlib
import importlib.util
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from judge_path_support import cases_of

import apps.phantom_invoices.detectors  # noqa: F401  (registers the pi.* detectors)
import apps.phantom_invoices.settings as pi_settings
import apps.vampire_fees.detectors  # noqa: F401  (registers the vf.* detectors)
import apps.vampire_fees.settings as vf_settings
import apps.zombie_subscriptions.detectors  # noqa: F401  (registers the zs.* detectors)
import apps.zombie_subscriptions.settings as zs_settings
from apps.zombie_subscriptions.detectors.utils import normalise_alias_map, normalise_date_map

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ledger_scan.py"
SAMPLES = ROOT / "data" / "samples"
PHANTOM_DEMO = SAMPLES / "phantom_demo"

ZOMBIE_CSV = SAMPLES / "zombie_demo_statement.csv"
ZOMBIE_N43 = SAMPLES / "zombie_demo_statement.n43"
VAMPIRE_CSV = SAMPLES / "vampire_demo_statement.csv"
VAMPIRE_N43 = SAMPLES / "vampire_demo_statement.n43"

SEVERITIES = ("critical", "warning", "info")
EUROPEAN_AMOUNT = re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d{2} [A-Z]{3}")
ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


@pytest.fixture(scope="module")
def scan_module() -> ModuleType:
    """Load scripts/ledger_scan.py by path, as the command line would run it."""
    spec = importlib.util.spec_from_file_location("ledger_scan", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ledger_scan"] = module
    spec.loader.exec_module(module)
    return module


def run(module: ModuleType, *argv: object) -> str:
    """Run main(argv) in process; return what it printed. The exit code must be 0."""
    out = io.StringIO()
    code = module.main([str(arg) for arg in argv], out)
    assert code == 0
    return out.getvalue()


def scan(module: ModuleType, *argv: object) -> dict[str, Any]:
    """Run the scan subcommand and parse its JSON."""
    return json.loads(run(module, "scan", *argv))


def alert_ids(payload: dict[str, Any], app: str) -> list[str]:
    """Return the sorted alert ids of one app in a scan result."""
    return sorted(a["alert_id"] for a in payload["alerts"] if a["app"] == app)


# --- The ids the pages would show ------------------------------------------------------------


def zombie_ids(path: Path) -> list[str]:
    """Alert ids of the Zombie page pipeline with no aliases and no cancellation dates."""
    config = zs_settings.load_config(ROOT / "apps" / "zombie_subscriptions" / "config.toml")
    pipeline = zs_settings.run_pipeline(
        path.name,
        path.read_bytes(),
        aliases=normalise_alias_map({}),
        cancellation_dates=normalise_date_map({}),
        cpi=zs_settings.load_cpi(config, ROOT),
    )
    return sorted(alert.id for alert in pipeline.alerts)


def vampire_ids(path: Path) -> list[str]:
    """Alert ids of the Vampire page pipeline for a statement file."""
    config = vf_settings.load_config(ROOT / "apps" / "vampire_fees" / "config.toml")
    pipeline = vf_settings.run_pipeline(
        path.name, path.read_bytes(), vocabulary=vf_settings.load_vocabulary(config)
    )
    return sorted(alert.id for alert in pipeline.alerts)


def phantom_ids(fmt: str) -> list[str]:
    """Alert ids of the Phantom page pipeline on its demo, in the given demo format."""
    config = pi_settings.load_config(ROOT / "apps" / "phantom_invoices" / "config.toml")
    demo = pi_settings.demo_inputs(config, ROOT, fmt)  # type: ignore[arg-type]
    pipeline = pi_settings.run_pipeline(demo.invoices, demo.suppliers, demo.payments, demo.as_of)
    return sorted(alert.id for result in pipeline.results for alert in result.alerts)


def phantom_args(fmt: str) -> list[str]:
    """The command-line arguments that feed the Phantom demo in one format."""
    if fmt == "real":
        invoices = sorted(str(p) for p in (PHANTOM_DEMO / "facturae").glob("*.xml"))
        payments = PHANTOM_DEMO / "payments.n43"
    else:
        invoices = [str(PHANTOM_DEMO / "invoices.csv")]
        payments = PHANTOM_DEMO / "payments.csv"
    return [
        *invoices,
        "--suppliers",
        str(PHANTOM_DEMO / "suppliers.csv"),
        "--payments",
        str(payments),
    ]


# --- Same alerts as the pages ----------------------------------------------------------------


@pytest.mark.parametrize("path", [ZOMBIE_CSV, ZOMBIE_N43])
def test_scan_zombie_statement_gives_the_page_alert_ids(scan_module: ModuleType, path: Path):
    payload = scan(scan_module, path)
    expected = zombie_ids(path)
    assert expected
    assert alert_ids(payload, "zombie_subscriptions") == expected


@pytest.mark.parametrize("path", [VAMPIRE_CSV, VAMPIRE_N43])
def test_scan_vampire_statement_gives_the_page_alert_ids(scan_module: ModuleType, path: Path):
    payload = scan(scan_module, path)
    expected = vampire_ids(path)
    assert expected
    assert alert_ids(payload, "vampire_fees") == expected


def test_scan_vampire_csv_matches_the_judge_path_helpers(scan_module: ModuleType):
    payload = scan(scan_module, VAMPIRE_CSV)
    assert alert_ids(payload, "vampire_fees") == sorted(c.alert.id for c in cases_of("vf"))


@pytest.mark.parametrize("fmt", ["csv", "real"])
def test_scan_phantom_demo_gives_the_page_alert_ids(scan_module: ModuleType, fmt: str):
    payload = scan(scan_module, *phantom_args(fmt))
    expected = phantom_ids(fmt)
    assert expected
    assert alert_ids(payload, "phantom_invoices") == expected


def test_scan_phantom_csv_matches_the_judge_path_helpers(scan_module: ModuleType):
    payload = scan(scan_module, *phantom_args("csv"))
    assert alert_ids(payload, "phantom_invoices") == sorted(c.alert.id for c in cases_of("pi"))


def test_statement_and_invoices_in_one_call_give_both_sets(scan_module: ModuleType):
    payload = scan(scan_module, ZOMBIE_CSV, *phantom_args("csv"))
    assert alert_ids(payload, "zombie_subscriptions") == zombie_ids(ZOMBIE_CSV)
    assert alert_ids(payload, "phantom_invoices") == phantom_ids("csv")


def test_as_of_is_passed_to_the_invoice_checks(scan_module: ModuleType):
    early = scan(scan_module, *phantom_args("csv"), "--as-of", "2000-01-01")
    default = scan(scan_module, *phantom_args("csv"))
    assert early["alerts"] != default["alerts"]


# --- Files -----------------------------------------------------------------------------------


def test_file_reports_hold_hash_kind_format_and_counts(scan_module: ModuleType):
    payload = scan(scan_module, ZOMBIE_N43, *phantom_args("real")[:1], *phantom_args("csv")[:1])
    by_name = {Path(f["path"]).name: f for f in payload["files"]}
    n43 = by_name[ZOMBIE_N43.name]
    assert n43["sha256"] == hashlib.sha256(ZOMBIE_N43.read_bytes()).hexdigest()
    assert (n43["kind"], n43["format"]) == ("bank_statement", "norma43")
    assert n43["rows"] > 0 and isinstance(n43["quarantined"], int) and n43["error"] is None
    [facturae] = [f for f in payload["files"] if f["format"] == "facturae"]
    assert facturae["kind"] == "invoice" and facturae["error"] is None
    invoices = by_name["invoices.csv"]
    assert (invoices["kind"], invoices["format"]) == ("invoice", "csv")
    assert invoices["rows"] > 0


def test_supplier_and_payment_files_are_reported_with_their_kind(scan_module: ModuleType):
    payload = scan(scan_module, *phantom_args("csv"))
    kinds = {Path(f["path"]).name: f["kind"] for f in payload["files"]}
    assert kinds["suppliers.csv"] == "supplier_master"
    assert kinds["payments.csv"] == "payments"


# --- Stable output ---------------------------------------------------------------------------


def test_two_runs_give_identical_bytes(scan_module: ModuleType):
    for args in ([ZOMBIE_CSV], [VAMPIRE_N43], phantom_args("real")):
        first = run(scan_module, "scan", *args)
        second = run(scan_module, "scan", *args)
        assert first.encode("utf-8") == second.encode("utf-8")
        assert first.isascii()


def test_a_key_or_a_model_in_the_environment_changes_nothing(
    scan_module: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    before = run(scan_module, "scan", ZOMBIE_CSV)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-used")
    monkeypatch.setitem(sys.modules, "openai", None)
    assert run(scan_module, "scan", ZOMBIE_CSV) == before


def test_keys_come_in_a_fixed_order(scan_module: ModuleType):
    payload = scan(scan_module, ZOMBIE_CSV, VAMPIRE_CSV)
    assert list(payload) == ["kit_version", "files", "alerts"]
    assert isinstance(payload["kit_version"], str) and payload["kit_version"]
    assert list(payload["files"][0]) == [
        "path",
        "sha256",
        "kind",
        "format",
        "rows",
        "quarantined",
        "error",
    ]
    assert list(payload["alerts"][0]) == [
        "alert_id",
        "app",
        "detector",
        "severity",
        "title",
        "text",
        "source_refs",
        "rows",
        "drafts",
    ]


def test_alerts_are_ordered_by_severity_then_title(scan_module: ModuleType):
    payload = scan(scan_module, ZOMBIE_CSV, VAMPIRE_CSV, *phantom_args("csv"))
    keys = [(SEVERITIES.index(a["severity"]), a["title"]) for a in payload["alerts"]]
    assert len(keys) > 3
    assert keys == sorted(keys)


def test_money_is_european_text_and_dates_are_iso(scan_module: ModuleType):
    payload = scan(scan_module, ZOMBIE_CSV)
    rows = [row for a in payload["alerts"] for row in a["rows"]]
    assert rows
    for row in rows:
        assert EUROPEAN_AMOUNT.fullmatch(row["amount"]), row["amount"]
        assert ISO_DAY.fullmatch(row["date"]), row["date"]
        assert set(row) <= {
            "source_ref",
            "date",
            "amount",
            "flow",
            "counterparty",
            "description",
            "iban",
        }


def test_cited_rows_are_the_rows_named_by_source_refs(scan_module: ModuleType):
    payload = scan(scan_module, *phantom_args("csv"))
    assert payload["alerts"]
    for alert in payload["alerts"]:
        shown = {row["source_ref"] for row in alert["rows"]}
        assert shown <= set(alert["source_refs"])


def test_each_alert_carries_its_fixed_text_and_refs(scan_module: ModuleType):
    payload = scan(scan_module, ZOMBIE_CSV, VAMPIRE_CSV, *phantom_args("csv"))
    for alert in payload["alerts"]:
        assert alert["text"], alert["title"]
        assert alert["source_refs"]
        assert alert["severity"] in SEVERITIES


def test_drafts_are_en_and_es_or_null(scan_module: ModuleType):
    payload = scan(scan_module, ZOMBIE_CSV, VAMPIRE_CSV, *phantom_args("csv"))
    drafts = [a["drafts"] for a in payload["alerts"]]
    with_template = [d for d in drafts if d is not None]
    assert with_template
    for draft in with_template:
        assert list(draft) == ["en", "es"]
        assert all(isinstance(text, str) and text for text in draft.values())
    summary = [a for a in payload["alerts"] if a["detector"] == "vf.fee_summary"]
    assert summary
    assert all(a["drafts"] is None for a in summary)


# --- Files that cannot be read ---------------------------------------------------------------


def test_an_unreadable_file_is_reported_and_the_others_still_run(
    scan_module: ModuleType, tmp_path: Path
):
    missing = tmp_path / "missing.csv"
    payload = scan(scan_module, missing, ZOMBIE_CSV)
    bad, good = payload["files"]
    assert bad["path"] == str(missing)
    assert bad["error"] and bad["sha256"] is None and bad["kind"] is None
    assert bad["rows"] == 0 and bad["quarantined"] == 0
    assert good["error"] is None
    assert alert_ids(payload, "zombie_subscriptions") == zombie_ids(ZOMBIE_CSV)


def test_a_file_in_no_known_format_is_reported_and_the_others_still_run(
    scan_module: ModuleType, tmp_path: Path
):
    junk = tmp_path / "notes.txt"
    junk.write_text("just some words\n", encoding="utf-8")
    payload = scan(scan_module, junk, ZOMBIE_CSV)
    assert payload["files"][0]["kind"] == "unknown"
    assert payload["files"][0]["error"]
    assert alert_ids(payload, "zombie_subscriptions") == zombie_ids(ZOMBIE_CSV)


def test_an_empty_file_gives_no_alert_and_no_error(scan_module: ModuleType, tmp_path: Path):
    empty = tmp_path / "empty.csv"
    empty.write_bytes(b"")
    payload = scan(scan_module, empty)
    assert payload["alerts"] == []
    assert payload["files"][0]["kind"] == "empty"
    assert payload["files"][0]["error"] is None


def test_an_unreadable_supplier_file_does_not_stop_the_invoice_checks(
    scan_module: ModuleType, tmp_path: Path
):
    payload = scan(
        scan_module,
        PHANTOM_DEMO / "invoices.csv",
        "--suppliers",
        tmp_path / "no-master.csv",
        "--payments",
        PHANTOM_DEMO / "payments.csv",
    )
    master = [f for f in payload["files"] if f["kind"] is None]
    assert len(master) == 1 and master[0]["error"]
    assert alert_ids(payload, "phantom_invoices")


# --- check -----------------------------------------------------------------------------------


def gymplus_alert(payload: dict[str, Any]) -> dict[str, Any]:
    """The recurring-charge alert of GYMPLUS in a scan of the zombie demo."""
    found = [
        a
        for a in payload["alerts"]
        if a["detector"] == "zs.recurring_charge" and "GYMPLUS" in a["title"]
    ]
    assert found
    return found[0]


def check(module: ModuleType, alert_id: str, text: str, *files: object) -> dict[str, Any]:
    """Run the check subcommand and parse its JSON."""
    return json.loads(run(module, "check", "--alert-id", alert_id, "--text", text, *files))


def test_check_accepts_the_fixed_template_text_of_an_alert(scan_module: ModuleType):
    alert = gymplus_alert(scan(scan_module, ZOMBIE_CSV))
    result = check(scan_module, alert["alert_id"], alert["text"], ZOMBIE_CSV)
    assert result["passed"] is True
    assert result["rejected"] == []
    assert result["error"] is None


def test_check_rejects_an_invented_figure_for_the_gymplus_alert(scan_module: ModuleType):
    alert = gymplus_alert(scan(scan_module, ZOMBIE_CSV))
    text = f"GYMPLUS has cost you 539.40 EUR. Source: {alert['source_refs'][0]}."
    result = check(scan_module, alert["alert_id"], text, ZOMBIE_CSV)
    assert result["passed"] is False
    assert "539.40" in result["rejected"]
    assert result["error"] is None


def test_check_with_an_unknown_alert_id_fails_with_a_message(scan_module: ModuleType):
    result = check(scan_module, "0" * 64, "anything", ZOMBIE_CSV)
    assert result["passed"] is False
    assert result["rejected"] == []
    assert isinstance(result["error"], str) and result["error"]


def test_check_output_keys_and_bytes_are_stable(scan_module: ModuleType):
    alert = gymplus_alert(scan(scan_module, ZOMBIE_CSV))
    args = ("check", "--alert-id", alert["alert_id"], "--text", "x", ZOMBIE_CSV)
    first = run(scan_module, *args)
    assert first == run(scan_module, *args)
    assert list(json.loads(first)) == ["alert_id", "passed", "rejected", "error"]


# --- Bad arguments exit with 2 ---------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["scan"],
        ["frobnicate", "file.csv"],
        ["scan", "file.csv", "--as-of", "yesterday"],
        ["scan", "file.csv", "--as-of", "2026-02-30"],
        ["scan", "file.csv", "--as-of", "20261111"],
        ["check", "file.csv"],
        ["check", "--alert-id", "abc", "file.csv"],
        ["check", "--text", "words", "file.csv"],
        ["check", "--alert-id", "abc", "--text", "words"],
    ],
)
def test_bad_arguments_exit_with_code_2(scan_module: ModuleType, argv: list[str]):
    out = io.StringIO()
    with pytest.raises(SystemExit) as exit_info:
        scan_module.main(argv, out)
    assert exit_info.value.code == 2
    assert out.getvalue() == ""


# --- As a real command ----------------------------------------------------------------------


def test_the_script_runs_as_a_command_from_any_directory(scan_module: ModuleType, tmp_path: Path):
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "scan", str(ZOMBIE_CSV)],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        timeout=300,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    expected = run(scan_module, "scan", ZOMBIE_CSV).encode("utf-8")
    assert done.stdout.replace(b"\r\n", b"\n") == expected


def test_the_script_exits_with_2_on_bad_arguments(tmp_path: Path):
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "scan"],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        timeout=300,
    )
    assert done.returncode == 2
    assert done.stdout == b""


def test_the_command_never_calls_a_model_or_the_network():
    text = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("urllib", "requests", "socket", "import openai", "explain_with_meta"):
        assert forbidden not in text
