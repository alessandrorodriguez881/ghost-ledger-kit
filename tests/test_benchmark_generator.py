"""Tests of the benchmark scenario generator (Tasks BM2, BM3, BM4).

``scripts/generate_benchmark.py`` is loaded by path (scripts/ is not a package). The expected
values come from the requirements text (REQ-BM-02 to REQ-BM-10), never from the detectors. The
checkers for IBANs and tax ids are written here on purpose: the generator must not grade itself.
All data is synthetic (Finance Rules 5 and 6); nothing reads the clock or the network.
"""

import ast
import csv
import importlib.util
import io
import re
import sys
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import apps.phantom_invoices.detectors  # noqa: F401  (registers the pi.* detectors)
import apps.zombie_subscriptions.detectors  # noqa: F401  (registers the zs.* detectors)
from ledger_kit.detectors import registered_names
from ledger_kit.ingestion.invoice_reader import parse_invoice
from ledger_kit.ingestion.sniffer import read_bank_statement
from ledger_kit.ingestion.supplier_reader import parse_suppliers
from ledger_kit.utils.money import net_total, percent_of, round_to_cents

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate_benchmark.py"
SCENARIOS = 200
BANK_HEADER = "date,amount,currency,counterparty,description,iban"
ALLOWED_IMPORTS = {
    "csv",
    "io",
    "random",
    "collections.abc",
    "dataclasses",
    "datetime",
    "decimal",
    "typing",
    "ledger_kit.utils.money",
}
FORBIDDEN_NAMES = {"time", "urllib", "socket", "os", "sys", "subprocess", "requests"}
FORBIDDEN_ATTRIBUTES = {"now", "today", "utcnow", "getenv", "environ", "time", "urlopen"}
UPPER = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _load_generator() -> ModuleType:
    """Load scripts/generate_benchmark.py by path under its own name."""
    spec = importlib.util.spec_from_file_location("generate_benchmark", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_benchmark"] = module
    spec.loader.exec_module(module)
    return module


gen: Any = _load_generator()


@pytest.fixture(scope="module")
def zombie_all() -> list[Any]:
    """All default zombie scenarios."""
    return gen.build_scenarios(gen.BENCHMARK_SEED, "zombie", SCENARIOS)


@pytest.fixture(scope="module")
def phantom_all() -> list[Any]:
    """All default phantom scenarios."""
    return gen.build_scenarios(gen.BENCHMARK_SEED, "phantom", SCENARIOS)


# --- helpers -----------------------------------------------------------------------------------


def _rows(scenario: Any, file: str) -> list[dict[str, str]]:
    """The data rows of one file of a scenario as dicts."""
    return list(csv.DictReader(io.StringIO(scenario.files[file], newline="")))


def _lines(scenario: Any, file: str = "statement.csv") -> list[str]:
    """The lines of a file (the header first)."""
    return scenario.files[file].splitlines()


def _solo(app: str, case: Any, **kwargs: Any) -> Any:
    """A scenario that holds only the given case (no noise), built with explicit parameters."""
    builder = gen.Builder(app, 0)
    case(builder, **kwargs)
    return builder.scenario()


def _phantom_builder(as_of: date | None = None) -> Any:
    """A phantom builder with an optional fixed as_of date."""
    builder = gen.Builder("phantom", 0)
    if as_of is not None:
        builder.set_as_of(as_of)
    return builder


def _label_types(scenario: Any) -> list[str]:
    """The types of the labels of a scenario in creation order."""
    return [label.type for label in scenario.labels]


def _refs(file: str, *indexes: int) -> tuple[str, ...]:
    """Refs ``file:i`` for the given row indexes."""
    return tuple(f"{file}:{index}" for index in indexes)


# --- REQ-BM-02: independence -------------------------------------------------------------------


def _forbidden_imports(source: str) -> list[str]:
    """Imported modules of ``source`` that are not on the allow list."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
            found += [f"{node.module}.{alias.name}" for alias in node.names]
    allowed = ALLOWED_IMPORTS
    return sorted(
        {
            name
            for name in found
            if name not in allowed
            and not any(name.startswith(prefix + ".") for prefix in allowed)
            and not any(other.startswith(name + ".") for other in allowed)
        }
    )


def _upper_names(source: str) -> set[str]:
    """Module-level UPPER_CASE names assigned in ``source``."""
    names: set[str] = set()
    for node in ast.parse(source).body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        names |= {t.id for t in targets if isinstance(t, ast.Name) and UPPER.match(t.id)}
    return names


def _detector_constant_names() -> set[str]:
    """UPPER_CASE module-level names of every detector module, read from the source files."""
    paths = [
        *(ROOT / "apps" / "zombie_subscriptions" / "detectors").glob("*.py"),
        *(ROOT / "apps" / "phantom_invoices" / "detectors").glob("*.py"),
        *(ROOT / "ledger_kit" / "detectors").glob("*.py"),
    ]
    names: set[str] = set()
    for path in paths:
        names |= _upper_names(path.read_text(encoding="utf-8"))
    return names


def test_the_generator_imports_only_the_allowed_modules() -> None:
    assert _forbidden_imports(SCRIPT.read_text(encoding="utf-8")) == []


def test_a_detector_import_is_named_by_the_independence_check() -> None:
    bad = "from apps.phantom_invoices.detectors.duplicate_invoice import DUPLICATE_WINDOW_DAYS\n"

    found = _forbidden_imports(bad)

    assert "apps.phantom_invoices.detectors.duplicate_invoice" in found


def test_a_clean_import_block_passes_the_independence_check() -> None:
    good = (
        "import random\nimport json\nfrom datetime import date\nfrom decimal import Decimal\n"
        "from ledger_kit.utils.money import round_to_cents\n"
    )

    assert _forbidden_imports(good) == ["json"]
    assert _forbidden_imports(good.replace("import json\n", "")) == []


def test_the_generator_defines_no_name_that_a_detector_module_defines() -> None:
    detector_names = _detector_constant_names()
    assert "VAT_TOLERANCE" in detector_names and "MIN_OCCURRENCES_MONTHLY" in detector_names

    clash = _upper_names(SCRIPT.read_text(encoding="utf-8")) & detector_names

    assert clash == set(), f"generator redefines detector constants: {sorted(clash)}"


def test_a_redefined_detector_constant_is_named_by_the_check() -> None:
    source = "PRICE_INCREASE_MIN_RATIO = 0.05\n"

    assert _upper_names(source) & {"PRICE_INCREASE_MIN_RATIO"} == {"PRICE_INCREASE_MIN_RATIO"}


def test_the_generator_reads_no_clock_environment_or_network() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}

    assert names & FORBIDDEN_NAMES == set()
    assert attributes & FORBIDDEN_ATTRIBUTES == set()


# --- REQ-BM-03, 04: seed, ids, files -----------------------------------------------------------


def test_rng_seed_text() -> None:
    expected = gen.random.Random("2026:zombie:7").random()

    assert gen.seed_text(2026, "zombie", 7) == "2026:zombie:7"
    assert gen.Builder("zombie", 7, 2026).rng.random() == expected


@pytest.mark.parametrize("app", ["zombie", "phantom"])
def test_a_scenario_does_not_depend_on_the_size_of_the_run(app: str) -> None:
    alone = gen.build_scenario(gen.BENCHMARK_SEED, app, 7)
    in_ten = gen.build_scenarios(gen.BENCHMARK_SEED, app, 10)[7]
    again = gen.build_scenario(gen.BENCHMARK_SEED, app, 7)

    assert alone == in_ten == again


def test_the_scenario_of_the_full_run_equals_the_single_build(
    zombie_all: list[Any], phantom_all: list[Any]
) -> None:
    assert zombie_all[7] == gen.build_scenario(gen.BENCHMARK_SEED, "zombie", 7)
    assert phantom_all[7] == gen.build_scenario(gen.BENCHMARK_SEED, "phantom", 7)


@pytest.mark.parametrize("app", ["zombie", "phantom"])
def test_another_seed_gives_other_bytes(app: str) -> None:
    first = gen.build_scenario(2026, app, 7)
    second = gen.build_scenario(2027, app, 7)

    assert first.files != second.files


def test_ids_and_noise_only_share_at_the_default_size(
    zombie_all: list[Any], phantom_all: list[Any]
) -> None:
    assert [s.id for s in zombie_all] == [f"zs-{k:04d}" for k in range(SCENARIOS)]
    assert [s.id for s in phantom_all] == [f"pi-{k:04d}" for k in range(SCENARIOS)]
    assert zombie_all[0].id == "zs-0000" and zombie_all[1].id == "zs-0001"
    for scenarios in (zombie_all, phantom_all):
        assert sum(s.noise_only for s in scenarios) == 40
        assert all(s.noise_only == (k % 5 == 0) for k, s in enumerate(scenarios))


def test_noise_only_indexes_of_a_run_of_ten() -> None:
    scenarios = gen.build_scenarios(gen.BENCHMARK_SEED, "zombie", 10)

    assert [k for k, s in enumerate(scenarios) if s.noise_only] == [0, 5]


def test_noise_only_scenarios_have_no_label_and_the_others_at_least_one(
    zombie_all: list[Any], phantom_all: list[Any]
) -> None:
    for scenario in [*zombie_all, *phantom_all]:
        if scenario.noise_only:
            assert scenario.labels == ()
        else:
            assert len(scenario.labels) >= 1


def test_file_names_header_and_line_endings(zombie_all: list[Any], phantom_all: list[Any]) -> None:
    for scenario in zombie_all:
        assert list(scenario.files) == ["statement.csv"]
        assert _lines(scenario)[0] == BANK_HEADER
    for scenario in phantom_all:
        assert list(scenario.files) == ["invoices.csv", "suppliers.csv", "payments.csv"]
        assert _lines(scenario, "payments.csv")[0] == BANK_HEADER
        assert _lines(scenario, "suppliers.csv")[0] == "supplier_name,tax_id,iban"
        assert _lines(scenario, "invoices.csv")[0].startswith("invoice_number,supplier_name,")
    for scenario in [*zombie_all, *phantom_all]:
        for text in scenario.files.values():
            assert "\r" not in text and text.endswith("\n")


def test_the_context_is_json_able(zombie_all: list[Any], phantom_all: list[Any]) -> None:
    assert set(zombie_all[0].context) == {"aliases", "cancellation_dates"}
    assert set(phantom_all[0].context) == {"as_of"}
    assert date.fromisoformat(phantom_all[0].context["as_of"]) >= date(2025, 10, 1)


def test_the_generator_does_not_import_the_ingestion_or_detector_layers() -> None:
    names = set(vars(gen))
    assert not {"parse_csv", "read_bank_statement", "register", "run_all"} & names


# --- REQ-BM-09: the row table and the labels ---------------------------------------------------


def test_refs_come_from_tags_after_the_final_order() -> None:
    table = gen.RowTable({"f.csv": (("date", "name"), "date")})
    late = table.add("f.csv", {"date": "2025-03-01", "name": "a"}, ("", "", "a"))
    early = table.add("f.csv", {"date": "2025-01-01", "name": "b"}, ("", "", "b"))
    tie = table.add("f.csv", {"date": "2025-03-01", "name": "c"}, ("", "", "c"))

    table.resolve()

    assert table.ref_of(early) == "f.csv:0"
    assert table.ref_of(late) == "f.csv:1"
    assert table.ref_of(tie) == "f.csv:2"
    assert table.text("f.csv").splitlines() == [
        "date,name",
        "2025-01-01,b",
        "2025-03-01,a",
        "2025-03-01,c",
    ]


def test_a_file_without_order_column_keeps_insertion_order() -> None:
    table = gen.RowTable({"s.csv": (("name",), None)})
    first = table.add("s.csv", {"name": "z"}, ("", "", "z"))
    second = table.add("s.csv", {"name": "a"}, ("", "", "a"))

    table.resolve()

    assert (table.ref_of(first), table.ref_of(second)) == ("s.csv:0", "s.csv:1")


def test_an_unknown_tag_raises() -> None:
    table = gen.RowTable({"f.csv": (("date",), "date")})
    table.resolve()

    with pytest.raises(ValueError, match="unknown row tag"):
        table.ref_of("f.csv#7")


def test_a_label_without_rows_raises_with_its_id() -> None:
    with pytest.raises(ValueError, match=r"^label zs-0003/L2 cites no row$"):
        gen.Label("zs-0003/L2", "zs-0003", "zs.recurring_charge", ())


def test_a_label_citing_a_tag_that_was_never_added_stops_the_build() -> None:
    builder = gen.Builder("zombie", 0)
    builder.label("zs.recurring_charge", ["statement.csv#99"])

    with pytest.raises(ValueError, match="unknown row tag"):
        builder.scenario()


def test_a_label_without_tags_stops_the_build_with_its_id() -> None:
    builder = gen.Builder("zombie", 3)
    builder.label("zs.recurring_charge", [])

    with pytest.raises(ValueError, match="label zs-0003/L0 cites no row"):
        builder.scenario()


def test_label_and_negative_ids_follow_creation_order(zombie_all: list[Any]) -> None:
    for scenario in zombie_all:
        assert [x.id for x in scenario.labels] == [
            f"{scenario.id}/L{k}" for k in range(len(scenario.labels))
        ]
        assert [x.id for x in scenario.negatives] == [
            f"{scenario.id}/N{k}" for k in range(len(scenario.negatives))
        ]


def test_every_ref_of_every_label_and_negative_is_a_written_row(
    zombie_all: list[Any], phantom_all: list[Any]
) -> None:
    for scenario in [*zombie_all, *phantom_all]:
        for record in [*scenario.labels, *scenario.negatives]:
            assert record.rows
            assert set(record.rows) <= set(scenario.row_facts)
        for label in scenario.labels:
            assert set(label.context_rows) <= set(scenario.row_facts)


def test_label_rows_are_in_natural_order_without_repeats(
    zombie_all: list[Any], phantom_all: list[Any]
) -> None:
    for scenario in [*zombie_all, *phantom_all]:
        for label in scenario.labels:
            assert list(label.rows) == sorted(set(label.rows), key=gen.natural)


# --- REQ-BM-10: identifiers --------------------------------------------------------------------


def _mod97(iban: str) -> bool:
    """Test-local ISO 13616 check."""
    compact = iban.replace(" ", "").upper()
    rearranged = compact[4:] + compact[:4]
    return int("".join(str(int(char, 36)) for char in rearranged)) % 97 == 1


def _correct_national_digits(compact: str) -> str:
    """Test-local correct Spanish control digits of a compact ES IBAN."""
    weights = (1, 2, 4, 8, 5, 10, 9, 7, 3, 6)

    def digit(text: str) -> int:
        total = sum(int(d) * w for d, w in zip(text, weights, strict=True))
        value = 11 - total % 11
        return {10: 1, 11: 0}.get(value, value)

    bban = compact[4:]
    return f"{digit('00' + bban[:8])}{digit(bban[10:])}"


def _cif_control_digit(body: str) -> int:
    """Test-local correct control digit of a type-B CIF."""
    total = 0
    for position, char in enumerate(body, start=1):
        value = int(char)
        if position % 2 == 1:
            value = value * 2
            value = value // 10 + value % 10
        total += value
    return (10 - total % 10) % 10


def _tax_id_is_wrong(tax_id: str) -> bool:
    """True when the control character of a CIF/NIF is not the correct one."""
    if tax_id.startswith("B"):
        return int(tax_id[8]) != _cif_control_digit(tax_id[1:8])
    letters = "TRWAGMYFPDXBNJZSQVHLCKE"
    return tax_id[8] != letters[int(tax_id[:8]) % 23]


def test_the_test_local_checkers_agree_with_the_documented_examples() -> None:
    assert _mod97("ES88 2100 0418 5602 0005 1332")
    assert _correct_national_digits("ES8821000418560200051332") == "45"
    assert not _tax_id_is_wrong("00000000T")  # correct letter, so it must not be used
    assert _tax_id_is_wrong("00000001T") and _tax_id_is_wrong("B00000001")


def test_generated_ibans_have_a_valid_checksum_and_wrong_national_digits() -> None:
    for k in range(50):
        compact = gen.make_iban("2100", "0418", f"{k:010d}")
        assert _mod97(compact)
        assert compact[12:14] != _correct_national_digits(compact)
    assert not _mod97(gen.break_checksum(gen.make_iban("2100", "0418", "0200051332")))
    assert "-" in gen.hyphenate_iban(gen.make_iban("2100", "0418", "0200051332"))


def test_generated_tax_ids_have_a_wrong_control_character() -> None:
    for k in (1, 2, 3, 99, 1234567):
        assert _tax_id_is_wrong(gen.make_cif(k))
    for n in (1, 2, 22, 24, 12345678, 99999999):
        assert _tax_id_is_wrong(gen.make_nif(n))


def test_every_master_tax_id_and_valid_iban_follows_finance_rule_5(phantom_all: list[Any]) -> None:
    for scenario in phantom_all:
        broken_master = {
            ref
            for label in scenario.labels
            if label.type == gen.IBAN_BAD
            for ref in label.rows
            if ref.startswith("suppliers.csv:")
        }
        for index, row in enumerate(_rows(scenario, "suppliers.csv")):
            assert _tax_id_is_wrong(row["tax_id"]), row["tax_id"]
            iban = row["iban"]
            if f"suppliers.csv:{index}" in broken_master:
                assert not _mod97(iban)
            else:
                assert _mod97(iban)
                assert iban.replace(" ", "")[12:14] != _correct_national_digits(
                    iban.replace(" ", "")
                )


def test_no_invalid_iban_outside_the_planted_cases(phantom_all: list[Any]) -> None:
    for scenario in phantom_all:
        planted = {
            ref for label in scenario.labels if label.type == gen.IBAN_BAD for ref in label.rows
        }
        for index, row in enumerate(_rows(scenario, "invoices.csv")):
            iban = row["iban"]
            if iban and f"invoices.csv:{index}" not in planted:
                assert _mod97(iban), (scenario.id, iban)
        for index, row in enumerate(_rows(scenario, "payments.csv")):
            if row["iban"]:
                assert _mod97(row["iban"]), (scenario.id, row["iban"])


def test_no_e_mail_or_phone_number_in_any_file(
    zombie_all: list[Any], phantom_all: list[Any]
) -> None:
    for scenario in [*zombie_all, *phantom_all]:
        for text in scenario.files.values():
            assert "@" not in text
            assert not re.search(r"\+\d{2}", text)


# --- REQ-BM-05: catalogue ----------------------------------------------------------------------


def _uncovered(registered: list[str], types: tuple[str, ...]) -> list[str]:
    """One message per registered detector that no problem type names."""
    covered = {problem.split("/")[0] for problem in types}
    return [
        f"registered detector {name} has no benchmark problem type"
        for name in registered
        if name not in covered
    ]


def test_every_registered_detector_has_a_problem_type() -> None:
    registered = registered_names("zs") + registered_names("pi")
    types = gen.ZOMBIE_TYPES + gen.PHANTOM_TYPES

    assert len(registered_names("zs")) == 5 and len(registered_names("pi")) == 4
    assert _uncovered(registered, types) == []
    assert {problem.split("/")[0] for problem in types} == set(registered)


def test_an_unknown_registered_detector_is_named() -> None:
    registered = [*registered_names("zs"), "zs.late_fee"]

    assert _uncovered(registered, gen.ZOMBIE_TYPES) == [
        "registered detector zs.late_fee has no benchmark problem type"
    ]


def test_the_catalogue_has_sixteen_types() -> None:
    assert len(gen.ZOMBIE_TYPES) == 5 and len(gen.PHANTOM_TYPES) == 11
    assert len(set(gen.ZOMBIE_TYPES + gen.PHANTOM_TYPES)) == 16


def test_17_cases_and_14_hard_negatives_per_app() -> None:
    for app in ("zombie", "phantom"):
        cases, negatives = gen.CATALOGUE[app]
        assert len(cases) == 17 and len(negatives) == 14
        assert len({spec.id for spec in cases + negatives}) == 31
        assert len({spec.name for spec in cases + negatives}) == 31


def test_label_free_kinds_are_the_noise_only_pool() -> None:
    zombie_free = [spec.id for spec in gen.ZOMBIE_NEGATIVES if spec.label_free]
    phantom_free = [spec.id for spec in gen.PHANTOM_NEGATIVES if spec.label_free]

    assert zombie_free == [f"NZ0{k}" for k in range(1, 9)]
    assert phantom_free == [spec.id for spec in gen.PHANTOM_NEGATIVES]


# --- coverage at the default size (REQ-BM-05, 06, 07) -------------------------------------------


def _schedule(app: str, index: int) -> tuple[list[str], list[str]]:
    """(case ids, negative ids) of scenario ``index`` by the round-robin of design 2.2."""
    cases, negatives = gen.CATALOGUE[app]
    if index % 5 == 0:
        free = [spec for spec in negatives if spec.label_free]
        q = index // 5
        return [], [free[(4 * q + j) % len(free)].id for j in range(4)]
    p = index - index // 5 - 1
    return (
        [cases[(3 * p + j) % len(cases)].id for j in range(3)],
        [negatives[(2 * p + j) % len(negatives)].id for j in range(2)],
    )


@pytest.mark.parametrize("app", ["zombie", "phantom"])
def test_every_case_has_enough_instances(app: str) -> None:
    counts: Counter[str] = Counter()
    for index in range(SCENARIOS):
        counts.update(_schedule(app, index)[0])

    cases = gen.CATALOGUE[app][0]
    assert all(counts[spec.id] >= gen.MIN_LABELS_PER_CASE for spec in cases), counts


def test_every_zombie_type_has_enough_labels(zombie_all: list[Any]) -> None:
    counts = Counter(label.type for s in zombie_all for label in s.labels)

    assert set(counts) == set(gen.ZOMBIE_TYPES)
    assert all(counts[t] >= gen.MIN_LABELS_PER_TYPE for t in gen.ZOMBIE_TYPES), counts


def test_every_phantom_type_has_enough_labels(phantom_all: list[Any]) -> None:
    counts = Counter(label.type for s in phantom_all for label in s.labels)

    assert set(counts) == set(gen.PHANTOM_TYPES)
    assert all(counts[t] >= gen.MIN_LABELS_PER_TYPE for t in gen.PHANTOM_TYPES), counts


@pytest.mark.parametrize("app", ["zombie", "phantom"])
def test_every_hard_negative_kind_has_enough_instances(
    app: str, zombie_all: list[Any], phantom_all: list[Any]
) -> None:
    scenarios = zombie_all if app == "zombie" else phantom_all
    counts = Counter(n.kind for s in scenarios for n in s.negatives)

    kinds = [spec.name for spec in gen.CATALOGUE[app][1]]
    assert set(counts) == set(kinds)
    assert all(counts[kind] >= gen.MIN_INSTANCES_PER_NEGATIVE for kind in kinds), counts


def test_the_schedule_names_the_negatives_that_were_built(zombie_all: list[Any]) -> None:
    names = {spec.id: spec.name for spec in gen.ZOMBIE_NEGATIVES}
    for index in (0, 1, 2, 5, 6, 10, 99):
        expected = [names[x] for x in _schedule("zombie", index)[1]]
        assert [n.kind for n in zombie_all[index].negatives] == expected


# --- REQ-BM-06: golden zombie examples ---------------------------------------------------------

RECURRING = "zs.recurring_charge"


def test_z08_price_clear_golden() -> None:
    scenario = _solo(
        "zombie",
        gen.z08_price_clear,
        name="CLOUDVAULT",
        start=date(2025, 2, 3),
        base=Decimal("20.00"),
    )

    assert _lines(scenario) == [
        BANK_HEADER,
        "2025-02-03,-20.00,EUR,CLOUDVAULT,Monthly subscription,",
        "2025-03-05,-20.00,EUR,CLOUDVAULT,Monthly subscription,",
        "2025-04-04,-20.00,EUR,CLOUDVAULT,Monthly subscription,",
        "2025-05-04,-24.00,EUR,CLOUDVAULT,Monthly subscription,",
        "2025-06-03,-24.00,EUR,CLOUDVAULT,Monthly subscription,",
        "2025-07-03,-24.00,EUR,CLOUDVAULT,Monthly subscription,",
    ]
    rows = _refs("statement.csv", 0, 1, 2, 3, 4, 5)
    assert [(x.type, x.rows) for x in scenario.labels] == [
        (RECURRING, rows),
        ("zs.price_increase", rows),
    ]
    assert scenario.labels[0].id == "zs-0000/L0" and scenario.negatives == ()


def test_z10_exactly_five_percent_is_labelled_positive() -> None:
    scenario = _solo("zombie", gen.z10_price_plus5, name="CLOUDVAULT", start=date(2025, 2, 3))

    amounts = [row["amount"] for row in _rows(scenario, "statement.csv")]
    assert amounts == ["-20.00"] * 3 + ["-21.00"] * 3
    assert _label_types(scenario) == [RECURRING, "zs.price_increase"]


def test_price_below_threshold_is_a_series_without_a_price_label() -> None:
    scenario = _solo(
        "zombie", gen.nz09_price_below_threshold, name="CLOUDVAULT", start=date(2025, 2, 3)
    )

    amounts = [row["amount"] for row in _rows(scenario, "statement.csv")]
    assert amounts == ["-100.00"] * 4 + ["-103.90"] * 2
    assert _label_types(scenario) == [RECURRING]
    assert [n.kind for n in scenario.negatives] == ["price_below_threshold"]


def test_price_decrease_is_a_series_without_a_price_label() -> None:
    scenario = _solo("zombie", gen.nz10_price_decrease, name="CLOUDVAULT", start=date(2025, 2, 3))

    amounts = [row["amount"] for row in _rows(scenario, "statement.csv")]
    assert amounts == ["-15.99"] * 3 + ["-12.99"] * 3
    assert _label_types(scenario) == [RECURRING]


def test_z15_trial_edge_golden() -> None:
    scenario = _solo(
        "zombie",
        gen.z15_trial_edge,
        name="CLOUDVAULT",
        trial_day=date(2025, 2, 3),
        price=Decimal("14.99"),
    )

    rows = _rows(scenario, "statement.csv")
    assert (rows[0]["date"], rows[0]["amount"]) == ("2025-02-03", "-1.00")
    assert (rows[1]["date"], rows[1]["amount"]) == ("2025-03-10", "-14.99")
    assert [(x.type, x.rows) for x in scenario.labels] == [
        (RECURRING, _refs("statement.csv", 1, 2, 3, 4, 5, 6)),
        ("zs.free_trial_to_paid", _refs("statement.csv", 0, 1, 2, 3, 4, 5, 6)),
    ]


def test_z14_trial_clear_uses_a_049_token_14_days_before() -> None:
    scenario = _solo("zombie", gen.z14_trial_clear, name="CLOUDVAULT", trial_day=date(2025, 2, 3))

    rows = _rows(scenario, "statement.csv")
    assert (rows[0]["date"], rows[0]["amount"]) == ("2025-02-03", "-0.49")
    assert rows[1]["date"] == "2025-02-17"


def test_trial_too_early_has_no_trial_label() -> None:
    scenario = _solo(
        "zombie", gen.nz11_trial_too_early, name="CLOUDVAULT", trial_day=date(2025, 2, 2)
    )

    rows = _rows(scenario, "statement.csv")
    assert (rows[0]["date"], rows[0]["amount"]) == ("2025-02-02", "-1.00")
    assert rows[1]["date"] == "2025-03-10"
    assert _label_types(scenario) == [RECURRING]


def test_trial_amount_above_has_no_trial_label() -> None:
    scenario = _solo("zombie", gen.nz12_trial_amount_above, name="CLOUDVAULT")

    assert _rows(scenario, "statement.csv")[0]["amount"] == "-1.01"
    assert _label_types(scenario) == [RECURRING]


def test_z17_cancel_edge_golden() -> None:
    scenario = _solo(
        "zombie",
        gen.z17_cancel_edge,
        name="GYMPLUS",
        start=date(2025, 3, 1),
        price=Decimal("8.99"),
    )

    dates = [row["date"] for row in _rows(scenario, "statement.csv")]
    assert dates == ["2025-03-01", "2025-03-31", "2025-04-30", "2025-05-30", "2025-06-29"]
    assert scenario.context["cancellation_dates"] == {"GYMPLUS": "2025-06-28"}
    assert [(x.type, x.rows) for x in scenario.labels] == [
        (RECURRING, _refs("statement.csv", 0, 1, 2, 3, 4)),
        ("zs.charges_after_cancellation", _refs("statement.csv", 4)),
    ]


def test_z16_cancel_clear_labels_the_charges_after_the_third() -> None:
    scenario = _solo("zombie", gen.z16_cancel_clear, name="GYMPLUS", start=date(2025, 3, 1))

    assert scenario.labels[1].type == "zs.charges_after_cancellation"
    assert scenario.labels[1].rows == _refs("statement.csv", 3, 4, 5)


def test_cancel_same_day_has_no_cancellation_label() -> None:
    scenario = _solo(
        "zombie",
        gen.nz13_cancel_same_day,
        name="GYMPLUS",
        start=date(2025, 3, 1),
        price=Decimal("8.99"),
    )

    assert scenario.context["cancellation_dates"] == {"GYMPLUS": "2025-06-29"}
    assert _label_types(scenario) == [RECURRING]


def test_z04_annual_pair_is_two_charges_365_days_apart() -> None:
    scenario = _solo("zombie", gen.z04_annual_pair, name="CLOUDVAULT", start=date(2025, 1, 5))

    assert [row["date"] for row in _rows(scenario, "statement.csv")] == ["2025-01-05", "2026-01-05"]
    assert _label_types(scenario) == [RECURRING]


def test_single_annual_charge_is_one_row_and_no_label() -> None:
    scenario = _solo("zombie", gen.nz03_single_annual, name="CLOUDVAULT", day=date(2025, 5, 5))

    assert _lines(scenario)[1:] == ["2025-05-05,-99.00,EUR,CLOUDVAULT,Annual plan,"]
    assert scenario.labels == ()
    assert [n.kind for n in scenario.negatives] == ["single_annual_charge"]


def test_z05_and_z06_sit_exactly_on_the_minimum_counts() -> None:
    monthly = _solo("zombie", gen.z05_monthly_min, name="CLOUDVAULT", start=date(2025, 1, 5))
    weekly = _solo("zombie", gen.z06_weekly_min, name="CLOUDVAULT", start=date(2025, 1, 5))

    assert len(_rows(monthly, "statement.csv")) == 3
    assert len(_rows(weekly, "statement.csv")) == 4
    two = _solo("zombie", gen.nz07_two_charges_only, name="CLOUDVAULT", start=date(2025, 1, 5))
    assert len(_rows(two, "statement.csv")) == 2 and two.labels == ()


def test_z07_gaps_alternate_33_and_27_and_nz08_uses_34() -> None:
    tolerant = _solo(
        "zombie", gen.z07_monthly_gaps_27_33, name="CLOUDVAULT", start=date(2025, 1, 1)
    )
    outside = _solo("zombie", gen.nz08_gap_34_days, name="CLOUDVAULT", start=date(2025, 1, 1))

    def gaps(scenario: Any) -> list[int]:
        days = [date.fromisoformat(r["date"]) for r in _rows(scenario, "statement.csv")]
        return [(b - a).days for a, b in zip(days, days[1:])]

    assert gaps(tolerant) == [33, 27, 33, 27]
    assert gaps(outside) == [34, 34, 34]


def test_duplicate_cases_label_both_series_and_the_pair() -> None:
    same = _solo("zombie", gen.z11_duplicate_same_key, name="CLOUDVAULT", start=date(2025, 1, 1))
    ratio = _solo(
        "zombie", gen.z13_duplicate_within_ratio, name="CLOUDVAULT", start=date(2025, 1, 1)
    )
    apart = _solo(
        "zombie", gen.nz14_parallel_amounts_differ, name="CLOUDVAULT", start=date(2025, 1, 1)
    )

    assert _label_types(same) == [RECURRING, RECURRING, "zs.duplicate_subscription"]
    assert _label_types(ratio) == _label_types(same)
    assert {row["amount"] for row in _rows(ratio, "statement.csv")} == {"-10.00", "-10.80"}
    assert _label_types(apart) == [RECURRING, RECURRING]
    assert {row["amount"] for row in _rows(apart, "statement.csv")} == {"-10.00", "-11.50"}
    assert len(same.labels[2].rows) == 8


def test_duplicate_alias_puts_the_alias_in_the_context() -> None:
    scenario = _solo("zombie", gen.z12_duplicate_alias, name="CLOUDVAULT", start=date(2025, 1, 1))

    names = {row["counterparty"] for row in _rows(scenario, "statement.csv")}
    assert names == {"CLOUDVAULT INTL 4412", "CLOUDVAULTCOM"}
    assert scenario.context["aliases"] == {"cloudvault": ["CLOUDVAULT INTL", "CLOUDVAULTCOM"]}


def test_weekly_groceries_shape() -> None:
    scenario = _solo("zombie", gen.nz01_weekly_groceries, name="FRESHCO", start=date(2025, 2, 5))

    rows = _rows(scenario, "statement.csv")
    dates = [date.fromisoformat(row["date"]) for row in rows]
    assert len(rows) == 26
    assert (dates[0], dates[-1]) == (date(2025, 2, 5), date(2025, 7, 30))
    assert all((b - a).days == 7 for a, b in zip(dates, dates[1:]))
    amounts = [-Decimal(row["amount"]) for row in rows]
    assert all(Decimal("15.00") <= amount <= Decimal("120.00") for amount in amounts)
    assert scenario.labels == ()
    assert len(scenario.negatives[0].rows) == 26


def test_fuel_gaps_and_amounts() -> None:
    scenario = _solo("zombie", gen.nz02_fuel, name="FUELCO", start=date(2025, 2, 5))

    rows = _rows(scenario, "statement.csv")
    dates = [date.fromisoformat(row["date"]) for row in rows]
    assert len(rows) == 20
    assert all(5 <= (b - a).days <= 12 for a, b in zip(dates, dates[1:]))
    assert all(Decimal("20.00") <= -Decimal(row["amount"]) <= Decimal("75.00") for row in rows)


def test_salary_credits_are_credits_and_yield_no_debit_row() -> None:
    scenario = _solo("zombie", gen.nz05_salary, name="ACMEWORKS", start=date(2025, 1, 31))

    transactions, quarantine = read_bank_statement(
        io.BytesIO(scenario.files["statement.csv"].encode("utf-8")), source_file="statement.csv"
    )
    assert quarantine == []
    assert [t.flow for t in transactions] == ["credit"] * 6
    assert len({t.amount for t in transactions}) == 1
    assert scenario.labels == ()


def test_refunds_are_two_or_three_credits() -> None:
    scenario = _solo("zombie", gen.nz06_refunds)

    amounts = [row["amount"] for row in _rows(scenario, "statement.csv")]
    assert 2 <= len(amounts) <= 3 and all(not a.startswith("-") for a in amounts)


def test_one_off_price_change_is_two_purchases_120_days_apart() -> None:
    scenario = _solo("zombie", gen.nz04_one_off_price_change, name="SHOPCO", start=date(2025, 2, 1))

    rows = _rows(scenario, "statement.csv")
    assert [(r["date"], r["amount"]) for r in rows] == [
        ("2025-02-01", "-129.00"),
        ("2025-06-01", "-149.00"),
    ]


def test_zombie_noise_rows_are_one_off_merchants(zombie_all: list[Any]) -> None:
    scenario = zombie_all[0]
    cited = {ref for n in scenario.negatives for ref in n.rows}
    rows = _rows(scenario, "statement.csv")
    one_offs = [
        row["counterparty"]
        for index, row in enumerate(rows)
        if f"statement.csv:{index}" not in cited and row["description"] == "Purchase"
    ]

    assert 15 <= len(one_offs) <= 40
    assert len(set(one_offs)) == len(one_offs)
    transfers = [r for r in rows if r["description"] == "Transfer"]
    assert 2 <= len(transfers) <= 4


def test_every_zombie_scenario_has_at_most_200_data_rows(zombie_all: list[Any]) -> None:
    assert max(len(_rows(s, "statement.csv")) for s in zombie_all) <= gen.MAX_STATEMENT_ROWS


def test_weekly_groceries_amounts_are_never_redrawn_to_avoid_a_pattern() -> None:
    first = _solo("zombie", gen.nz01_weekly_groceries, name="FRESHCO", start=date(2025, 2, 5))
    second = _solo("zombie", gen.nz01_weekly_groceries, name="FRESHCO", start=date(2025, 2, 5))

    assert first == second


def test_zombie_files_round_trip_through_the_real_reader(zombie_all: list[Any]) -> None:
    for scenario in zombie_all:
        data = scenario.files["statement.csv"].encode("utf-8")
        result = read_bank_statement(io.BytesIO(data), source_file="statement.csv")
        transactions, quarantine = result

        assert quarantine == [], scenario.id
        assert len(transactions) == len(_rows(scenario, "statement.csv"))
        assert {t.source_ref for t in transactions} == set(scenario.row_facts)
        for tx in transactions:
            day, amount, name = scenario.row_facts[tx.source_ref]
            assert (tx.date.isoformat(), tx.amount, tx.counterparty) == (day, Decimal(amount), name)


# --- REQ-BM-06, 07, 10: phantom ----------------------------------------------------------------

DAY = date(2025, 3, 3)


def _supplier_and_builder(as_of: date | None = None) -> tuple[Any, Any]:
    """A phantom builder and one fresh supplier."""
    builder = _phantom_builder(as_of)
    return builder, builder.supplier()


def test_p10b_vat_off_two_cents_golden() -> None:
    builder, sup = _supplier_and_builder()
    gen.p10b_vat_off_2_cents(builder, sup=sup, issue=DAY, base=Decimal("100.00"))
    scenario = builder.scenario()

    [invoice] = _rows(scenario, "invoices.csv")
    assert (invoice["base_amount"], invoice["vat_rate"]) == ("100.00", "21")
    assert (invoice["vat_amount"], invoice["total"]) == ("21.02", "121.02")
    assert [(x.type, x.rows) for x in scenario.labels] == [
        ("pi.vat_error/vat_amount_mismatch", _refs("invoices.csv", 0))
    ]


def test_vat_off_by_one_cent_has_no_label() -> None:
    builder, sup = _supplier_and_builder()
    gen.np09_vat_off_by_one_cent(builder, sup=sup, issue=DAY, base=Decimal("100.00"))
    scenario = builder.scenario()

    [invoice] = _rows(scenario, "invoices.csv")
    assert (invoice["vat_amount"], invoice["total"]) == ("21.01", "121.01")
    assert scenario.labels == ()
    assert [n.kind for n in scenario.negatives] == ["vat_off_by_one_cent"]


def test_total_cases_keep_the_vat_correct() -> None:
    for case, extra in ((gen.p11a_total_clear, "10.00"), (gen.p11b_total_off_2_cents, "0.02")):
        builder, sup = _supplier_and_builder()
        case(builder, sup=sup, issue=DAY, base=Decimal("100.00"))

        [invoice] = _rows(builder.scenario(), "invoices.csv")
        assert invoice["vat_amount"] == "21.00"
        assert Decimal(invoice["total"]) == Decimal("121.00") + Decimal(extra)


def test_p10a_states_a_vat_of_12_10_on_a_base_of_100() -> None:
    builder, sup = _supplier_and_builder()
    gen.p10a_vat_clear(builder, sup=sup, issue=DAY, base=Decimal("100.00"))

    [invoice] = _rows(builder.scenario(), "invoices.csv")
    assert invoice["vat_rate"] == "21"
    assert (invoice["vat_amount"], invoice["total"]) == ("12.10", "112.10")


def test_p12_rate_20_is_consistent_with_itself() -> None:
    builder, sup = _supplier_and_builder()
    gen.p12_rate_not_allowed(builder, sup=sup, issue=DAY, base=Decimal("100.00"))
    scenario = builder.scenario()

    [invoice] = _rows(scenario, "invoices.csv")
    assert invoice["vat_rate"] == "20"
    assert (invoice["vat_amount"], invoice["total"]) == ("20.00", "120.00")
    assert _label_types(scenario) == ["pi.vat_error/vat_rate_not_allowed"]


def _dup_rows(scenario: Any) -> list[tuple[str, str, str]]:
    """(number, issue date, total) of every invoice row."""
    rows = _rows(scenario, "invoices.csv")
    return [(r["invoice_number"], r["issue_date"], r["total"]) for r in rows]


def test_p04_and_np08_around_the_six_day_limit() -> None:
    numbers = ("FAC-0201", "FAC-0202")
    inside, sup = _supplier_and_builder()
    gen.p04_dup_total_6_days(inside, sup=sup, issue=DAY, base=Decimal("200.00"), numbers=numbers)
    outside, sup2 = _supplier_and_builder()
    gen.np08_same_total_7_days_apart(
        outside, sup=sup2, issue=DAY, base=Decimal("200.00"), numbers=numbers
    )

    first, second = inside.scenario(), outside.scenario()
    assert _dup_rows(first) == [
        ("FAC-0201", "2025-03-03", "242.00"),
        ("FAC-0202", "2025-03-09", "242.00"),
    ]
    assert _dup_rows(second)[1] == ("FAC-0202", "2025-03-10", "242.00")
    assert [(x.type, x.rows) for x in first.labels] == [
        ("pi.duplicate_invoice/same_total_close_dates", _refs("invoices.csv", 0, 1))
    ]
    assert second.labels == ()


def test_p02_and_np07_around_the_180_day_limit() -> None:
    inside, sup = _supplier_and_builder()
    gen.p02_dup_same_number_179(inside, sup=sup, issue=date(2025, 1, 10))
    outside, sup2 = _supplier_and_builder()
    gen.np07_numbering_restart_180(outside, sup=sup2, issue=date(2025, 1, 10))

    first, second = inside.scenario(), outside.scenario()
    rows = _dup_rows(first)
    assert rows[0][0] == rows[1][0] and (rows[0][1], rows[1][1]) == ("2025-01-10", "2025-07-08")
    assert _label_types(first) == ["pi.duplicate_invoice/same_number"]
    assert [r[1] for r in _dup_rows(second)] == ["2025-01-10", "2025-07-09"]
    assert second.labels == ()


def test_p01_yields_two_invoices_and_two_payments_of_the_same_amount() -> None:
    builder, sup = _supplier_and_builder()
    gen.p01_dup_same_number_clear(builder, sup=sup, issue=DAY)
    scenario = builder.scenario()

    invoices, payments = _rows(scenario, "invoices.csv"), _rows(scenario, "payments.csv")
    assert len(invoices) == 2 and len(payments) == 2
    assert invoices[0]["invoice_number"] == invoices[1]["invoice_number"]
    assert {p["amount"] for p in payments} == {f"-{invoices[0]['total']}"}
    assert (date.fromisoformat(invoices[1]["issue_date"]) - DAY).days == 2


def test_p03_and_np11_use_the_near_identical_number_pair() -> None:
    inside, sup = _supplier_and_builder()
    gen.p03_dup_near_identical(
        inside, sup=sup, issue=DAY, numbers=("F-2026-0042", "F2026-042"), base=Decimal("50.00")
    )
    outside, sup2 = _supplier_and_builder()
    gen.np11_near_number_totals_differ(
        outside, sup=sup2, issue=DAY, numbers=("F-2026-0042", "F2026-042"), base=Decimal("50.00")
    )

    first, second = inside.scenario(), outside.scenario()
    assert [r[2] for r in _dup_rows(first)] == ["60.50", "60.50"]
    assert [r[2] for r in _dup_rows(second)] == ["60.50", "60.51"]
    assert _label_types(first) == ["pi.duplicate_invoice/near_identical_number"]
    assert second.labels == ()


def test_p14_and_np10_around_the_overdue_limit() -> None:
    late, sup = _supplier_and_builder(date(2025, 4, 17))
    gen.p14_overdue_16(late, sup=sup)
    open_, sup2 = _supplier_and_builder(date(2025, 4, 16))
    gen.np10_open_at_due_plus_15(open_, sup=sup2)

    first, second = late.scenario(), open_.scenario()
    [invoice] = _rows(first, "invoices.csv")
    assert invoice["due_date"] == "2025-04-01" and first.context == {"as_of": "2025-04-17"}
    assert _rows(first, "payments.csv") == []
    assert [(x.type, x.rows) for x in first.labels] == [
        ("pi.reconciliation/invoice_overdue", _refs("invoices.csv", 0))
    ]
    assert _rows(second, "invoices.csv")[0]["due_date"] == "2025-04-01"
    assert second.labels == () and [n.kind for n in second.negatives] == ["open_at_due_plus_15"]


def test_p13_is_40_days_overdue() -> None:
    builder, sup = _supplier_and_builder(date(2025, 6, 30))
    gen.p13_overdue_clear(builder, sup=sup)

    [invoice] = _rows(builder.scenario(), "invoices.csv")
    assert invoice["due_date"] == "2025-05-21"


def test_iban_cases_cite_the_invoice_or_payment_and_keep_the_master_as_context() -> None:
    results = {}
    for name, case in (
        ("differs", gen.p05_iban_invoice_differs),
        ("payment", gen.p06_iban_payment_non_master),
        ("format", gen.p07_iban_invalid_format),
        ("checksum", gen.p08_iban_invalid_checksum),
    ):
        builder, sup = _supplier_and_builder()
        case(builder, sup=sup, issue=DAY)
        results[name] = (builder.scenario(), sup)

    differs, _ = results["differs"]
    assert differs.labels[0].rows == _refs("invoices.csv", 0)
    assert differs.labels[0].context_rows == _refs("suppliers.csv", 0)
    payment, _ = results["payment"]
    assert payment.labels[0].rows == _refs("payments.csv", 0)
    assert payment.labels[0].context_rows == _refs("suppliers.csv", 0)
    fmt, _ = results["format"]
    assert "-" in _rows(fmt, "invoices.csv")[0]["iban"]
    checksum, _ = results["checksum"]
    broken = _rows(checksum, "invoices.csv")[0]["iban"]
    assert not _mod97(broken) and re.fullmatch(r"ES\d{22}", broken.replace(" ", ""))


def test_p09_cites_the_master_row_only() -> None:
    builder = _phantom_builder()
    gen.p09_iban_invalid_master(builder)
    scenario = builder.scenario()

    assert _rows(scenario, "invoices.csv") == [] and _rows(scenario, "payments.csv") == []
    assert scenario.labels[0].rows == _refs("suppliers.csv", 0)
    assert not _mod97(_rows(scenario, "suppliers.csv")[0]["iban"])


def test_p15_is_a_payment_to_a_master_supplier_without_invoice() -> None:
    builder, sup = _supplier_and_builder(date(2025, 10, 1))
    gen.p15_payment_without_invoice(builder, sup=sup, day=date(2025, 5, 5), amount=Decimal("80.00"))
    scenario = builder.scenario()

    [payment] = _rows(scenario, "payments.csv")
    assert payment["counterparty"] == sup.name and payment["amount"] == "-80.00"
    assert _rows(scenario, "invoices.csv") == []
    assert scenario.labels[0].rows == _refs("payments.csv", 0)


def test_two_legit_ibans_hold_two_master_rows_with_one_tax_id() -> None:
    builder, sup = _supplier_and_builder()
    gen.np03_two_legit_ibans(builder, sup=sup, issue=DAY)
    scenario = builder.scenario()

    master = _rows(scenario, "suppliers.csv")
    assert len(master) == 2 and master[0]["tax_id"] == master[1]["tax_id"]
    assert master[0]["iban"] != master[1]["iban"] and _mod97(master[1]["iban"])
    second = master[1]["iban"]
    assert {r["iban"] for r in _rows(scenario, "invoices.csv")} == {second}
    assert {r["iban"] for r in _rows(scenario, "payments.csv")} == {second}
    assert scenario.labels == ()


def test_same_number_at_two_suppliers_has_two_masters_and_no_label() -> None:
    builder = _phantom_builder()
    gen.np01_same_number_two_suppliers(builder, issue=DAY, number="INV-0042")
    scenario = builder.scenario()

    invoices = _rows(scenario, "invoices.csv")
    assert {r["invoice_number"] for r in invoices} == {"INV-0042"}
    assert len({r["supplier_tax_id"] for r in invoices}) == 2
    assert len(_rows(scenario, "payments.csv")) == 2 and scenario.labels == ()


def test_same_amount_in_other_months_is_28_to_35_days_apart() -> None:
    builder, sup = _supplier_and_builder()
    gen.np02_same_amount_other_months(builder, sup=sup, issue=DAY)

    rows = _rows(builder.scenario(), "invoices.csv")
    first, second = (date.fromisoformat(row["issue_date"]) for row in rows)
    gap = (second - first).days
    assert 28 <= gap <= 35 and rows[0]["total"] == rows[1]["total"]
    assert (rows[0]["invoice_number"][-2:], rows[1]["invoice_number"][-2:]) == ("01", "02")


def test_late_and_last_day_payments() -> None:
    late, sup = _supplier_and_builder()
    gen.np04_paid_late_in_full(late, sup=sup, issue=DAY)
    last, sup2 = _supplier_and_builder()
    gen.np05_paid_on_last_matching_day(last, sup=sup2, issue=DAY)

    due = DAY + timedelta(days=30)
    late_payment = _rows(late.scenario(), "payments.csv")[0]["date"]
    last_payment = _rows(last.scenario(), "payments.csv")[0]["date"]
    assert late_payment == (due + timedelta(days=30)).isoformat()
    assert last_payment == (due + timedelta(days=60)).isoformat()


def test_iban_spelling_variant_and_missing_iban() -> None:
    spelled, sup = _supplier_and_builder()
    gen.np12_iban_spelling_variant(spelled, sup=sup, issue=DAY)
    missing, sup2 = _supplier_and_builder()
    gen.np14_missing_iban(missing, sup=sup2, issue=DAY)

    first, second = spelled.scenario(), missing.scenario()
    master = _rows(first, "suppliers.csv")[0]["iban"]
    assert _rows(first, "invoices.csv")[0]["iban"] == master.lower() != master
    assert _rows(second, "invoices.csv")[0]["iban"] == ""
    assert _rows(second, "payments.csv")[0]["iban"] != ""


def test_non_supplier_payments_use_accounts_outside_the_master() -> None:
    builder = _phantom_builder()
    builder.supplier()
    gen.np13_non_supplier_payments(builder)
    scenario = builder.scenario()

    master_ibans = {r["iban"] for r in _rows(scenario, "suppliers.csv")}
    payments = _rows(scenario, "payments.csv")
    assert payments and {p["iban"] for p in payments}.isdisjoint(master_ibans)
    assert any(not p["amount"].startswith("-") for p in payments)


def test_the_golden_rounding_table_matches_the_money_helpers() -> None:
    assert len(gen.ROUNDING_TABLE) == 7
    for base, rate, vat, total in gen.ROUNDING_TABLE:
        assert percent_of(Decimal(base), Decimal(rate)) == Decimal(vat)
        assert round_to_cents(net_total([Decimal(base), Decimal(vat)])) == Decimal(total)


def test_rounding_half_cent_writes_the_table_and_one_rate_as_21_00() -> None:
    builder, sup = _supplier_and_builder()
    gen.np06_rounding_half_cent(builder, sup=sup, issue=DAY)
    scenario = builder.scenario()

    rows = _rows(scenario, "invoices.csv")
    assert [(r["base_amount"], r["vat_rate"], r["vat_amount"], r["total"]) for r in rows] == list(
        gen.ROUNDING_TABLE
    )
    assert [r["vat_rate"] for r in rows].count("21.00") == 1
    assert scenario.labels == ()


def test_phantom_noise_has_two_to_five_suppliers_with_three_to_five_invoices(
    phantom_all: list[Any],
) -> None:
    scenario = phantom_all[0]
    rows = _rows(scenario, "invoices.csv")
    cited = {ref for n in scenario.negatives for ref in n.rows}
    noise = [row for index, row in enumerate(rows) if f"invoices.csv:{index}" not in cited]

    per_supplier = Counter(row["supplier_tax_id"] for row in noise)
    assert 2 <= len(per_supplier) and all(3 <= count <= 5 for count in per_supplier.values())


def test_every_phantom_invoice_is_paid_unless_it_is_an_overdue_one(phantom_all: list[Any]) -> None:
    for scenario in phantom_all:
        as_of = date.fromisoformat(scenario.context["as_of"])
        unpaid_refs = {
            ref
            for label in scenario.labels
            if label.type == "pi.reconciliation/invoice_overdue"
            for ref in label.rows
        } | {
            ref
            for negative in scenario.negatives
            if negative.kind == "open_at_due_plus_15"
            for ref in negative.rows
        }
        payments = [
            (r["counterparty"], r["amount"], date.fromisoformat(r["date"]))
            for r in _rows(scenario, "payments.csv")
        ]
        assert all(day <= as_of for _name, _amount, day in payments), scenario.id
        for index, row in enumerate(_rows(scenario, "invoices.csv")):
            if f"invoices.csv:{index}" in unpaid_refs:
                continue
            issue = date.fromisoformat(row["issue_date"])
            candidates = [
                p
                for p in payments
                if p[0] == row["supplier_name"]
                and p[1] == f"-{row['total']}"
                and timedelta(days=10) <= p[2] - issue <= timedelta(days=90)
            ]
            assert candidates, (scenario.id, row["invoice_number"])
            payments.remove(candidates[0])


def test_phantom_files_round_trip_through_the_real_readers(phantom_all: list[Any]) -> None:
    for scenario in phantom_all:
        invoices, bad_invoices = parse_invoice(
            io.BytesIO(scenario.files["invoices.csv"].encode("utf-8")),
            fmt="csv",
            source_file="invoices.csv",
        )
        suppliers, bad_suppliers = parse_suppliers(
            io.BytesIO(scenario.files["suppliers.csv"].encode("utf-8")),
            source_file="suppliers.csv",
        )
        payments, bad_payments = read_bank_statement(
            io.BytesIO(scenario.files["payments.csv"].encode("utf-8")),
            source_file="payments.csv",
        )

        assert bad_invoices == [] and bad_suppliers == [] and bad_payments == [], scenario.id
        loaded = {x.source_ref for x in [*invoices, *suppliers, *payments]}
        assert loaded == set(scenario.row_facts)
        for inv in invoices:
            day, total, number = scenario.row_facts[inv.source_ref]
            assert (inv.issue_date.isoformat(), inv.total, inv.invoice_number) == (
                day,
                Decimal(total),
                number,
            )
        for sup in suppliers:
            assert scenario.row_facts[sup.source_ref][2] == sup.supplier_name
        for pay in payments:
            day, amount, name = scenario.row_facts[pay.source_ref]
            assert (pay.date.isoformat(), pay.amount, pay.counterparty) == (
                day,
                Decimal(amount),
                name,
            )


# --- Task BM9: duplicate series are active (REQ-ZS-13a, REQ-ZS-17, D-BM-20) ---------------------

# REQ-ZS-13a: a monthly series is active when its last charge is within 30 + 3 days of the latest
# date of the ledger. Written here from the requirement; not read from a detector.
ACTIVE_DAYS_MONTHLY = 30 + 3


def _latest_date(scenario: Any) -> date:
    """The latest date of any row of a zombie scenario."""
    return max(date.fromisoformat(fact[0]) for fact in scenario.row_facts.values())


def _last_date(scenario: Any, refs: tuple[str, ...]) -> date:
    """The latest date among the given rows."""
    return max(date.fromisoformat(scenario.row_facts[ref][0]) for ref in refs)


def test_late_start_puts_the_last_row_in_the_final_days_of_the_window() -> None:
    for index in range(60):
        builder = gen.Builder("zombie", index)
        start = builder.late_start(90, slack=15)
        last = start + timedelta(days=90)

        assert gen.ZOMBIE_END - timedelta(days=30) <= last <= gen.ZOMBIE_END - timedelta(days=15)
        assert start >= gen.ZOMBIE_START


def test_late_start_without_slack_stays_in_the_final_thirty_days() -> None:
    lasts = {
        gen.Builder("zombie", index).late_start(30) + timedelta(days=30) for index in range(300)
    }

    assert max(lasts) <= gen.ZOMBIE_END
    assert min(lasts) >= gen.ZOMBIE_END - timedelta(days=30)
    assert len(lasts) > 1  # the position is drawn, not fixed


def test_every_planted_duplicate_is_made_of_two_series_that_are_active(
    zombie_all: list[Any],
) -> None:
    checked = 0
    for scenario in zombie_all:
        latest = _latest_date(scenario)
        for label in scenario.labels:
            if label.type != gen.DUPLICATE_SUB:
                continue
            series = [
                other
                for other in scenario.labels
                if other.type == gen.RECURRING and set(other.rows) <= set(label.rows)
            ]
            assert len(series) == 2, label.id
            for part in series:
                gap = (latest - _last_date(scenario, part.rows)).days
                assert gap <= ACTIVE_DAYS_MONTHLY, (label.id, part.id, gap)
            checked += 1
    assert checked >= gen.MIN_LABELS_PER_CASE


def test_the_parallel_amounts_differ_negative_is_active_so_it_can_fire(
    zombie_all: list[Any],
) -> None:
    checked = 0
    for scenario in zombie_all:
        latest = _latest_date(scenario)
        for negative in scenario.negatives:
            if negative.kind != "parallel_amounts_differ":
                continue
            by_amount: dict[str, list[str]] = {}
            for ref in negative.rows:
                by_amount.setdefault(scenario.row_facts[ref][1], []).append(ref)
            assert len(by_amount) == 2, negative.id
            for refs in by_amount.values():
                gap = (latest - _last_date(scenario, tuple(refs))).days
                assert gap <= ACTIVE_DAYS_MONTHLY, (negative.id, gap)
            checked += 1
    assert checked >= gen.MIN_INSTANCES_PER_NEGATIVE


def test_an_explicit_start_still_wins_over_the_late_start() -> None:
    start = date(2025, 1, 1)
    scenario = _solo("zombie", gen.z11_duplicate_same_key, name="CLOUDVAULT", start=start)

    assert min(fact[0] for fact in scenario.row_facts.values()) == "2025-01-01"
