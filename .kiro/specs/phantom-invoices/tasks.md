# phantom-invoices — Implementation Tasks

**Depends on**: the ledger-core tasks that carry **CR-LC-3** (requirements §14), all of which must be
done before Task P1:

| CR-LC-3 item | ledger-core task |
|---|---|
| a, b — `Invoice`, `Supplier`, `IngestionResult` generic | Task 2 (models), Task 8 (`normalise(kind=...)`), Task 9 (`parse_invoice`, `parse_suppliers`) |
| c — `Transaction.iban` read by `parse_csv` | Task 6 |
| d — `loaded_source_refs`, union property | Task 10 (base types), Task 11 (properties) |
| e — `percent_of`, `within_tolerance`, `net_total` | Task 3 |
| f — context-reading detectors may alert on an empty ledger | Task 10 |
| g — `row_columns`, `mask_iban`, public `fill_fallback` | Task 5 (`mask_iban`), Task 11a (explainer) |
| h — Finance Rule 5 identifiers; sample generator script | Task 13 (`scripts/generate_samples.py`, `data/samples/`) |

Tasks 1, 4, 7 and 12 of ledger-core are prerequisites of those tasks and are therefore also needed.
Nothing here modifies a file under `ledger_kit/`. Files outside `apps/phantom_invoices/` that this
spec does touch: `scripts/generate_samples.py` (new `phantom-demo` mode), `.gitattributes`,
`data/samples/phantom_demo/`, `data/samples/README.md`, `.kiro/steering/structure.md`.

Every task is **test-first**: write the tests, watch them fail, implement until they pass, then run
`ruff check` and `ruff format --check`. Tasks are in dependency order. Property tests use
`@settings(max_examples=200)` and never a function-scoped fixture (REQ-TST-09); no test reads the
system clock; fixtures use fictional names and the identifiers of Finance Rule 5 only. Every
detector test calls the detector directly with a `MappingProxyType` context and has one test
through `run_all(namespace="pi", context=...)` (REQ-PI-61). Every Tier 1 test asserts the exact
alert count, a non-empty `source_refs` pointing at the right rows, and `Alert.detector` equal to the
registered name. An app never imports a private (underscore) name from `ledger_kit` (DN-9): the
fallback filler is `from ledger_kit.explainer import fill_fallback`.

Section references (§) point to `design.md`; REQ ids to `requirements.md`. Test files live in
`apps/phantom_invoices/tests/` unless a path says otherwise.

---

## Task P1 — App package scaffold

**Covers**: REQ-PI-53 (no app-level `requirements.txt`), REQ-PI-14 (package layout), DN-9, §1

- [x] Write `apps/phantom_invoices/tests/test_pi_scaffold.py`:
  - `test_app_package_importable` — `import apps.phantom_invoices` and `apps.phantom_invoices.detectors` succeed under plain `pytest`.
  - `test_no_app_level_requirements_txt` — `apps/phantom_invoices/requirements.txt` does not exist; root `requirements.txt` exists.
  - `test_app_does_not_import_other_app` — no module under the app imports `apps.zombie_subscriptions`; `ledger_kit` imports nothing from `apps`.
  - `test_app_imports_no_private_ledger_kit_name` — an `ast` scan of every `.py` under `apps/phantom_invoices/` finds no `from ledger_kit... import _x` and no attribute access `ledger_kit....._x` on a name starting with an underscore (DN-9).
  - `test_no_clock_calls_in_package` — `ast` scan: no call to `today`, `now`, `utcnow` or `time.time` (REQ-PI-65, §16.4 part 1). Passes trivially now and guards every later task.
- [x] Create empty `apps/__init__.py` (skip if it exists), `apps/phantom_invoices/__init__.py`, `apps/phantom_invoices/detectors/__init__.py` (empty for now; Task P14 fills it), `apps/phantom_invoices/tests/` (no `__init__.py`).
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_scaffold.py -q` passes; `ruff check` clean.

---

## Task P2 — ledger-core contract smoke test

**Covers**: REQ-PI-01, REQ-PI-02, REQ-PI-14, requirements §14 (CR-LC-3 a–g), DN-9

- [x] Write `apps/phantom_invoices/tests/test_pi_ledger_core_contract.py`, one test per CR-LC-3 item, so a missing ledger-core piece fails here with a clear name instead of deep inside a detector:
  - `test_cr_lc_3a_invoice_model_and_reader` — `Invoice`, `parse_invoice`, `normalise(kind="invoice")` return `INVOICE_COLUMNS`.
  - `test_cr_lc_3b_supplier_model_and_reader` — `Supplier`, `parse_suppliers`, `normalise(kind="supplier")` return `SUPPLIER_COLUMNS`.
  - `test_cr_lc_3c_parse_csv_reads_iban_verbatim`.
  - `test_cr_lc_3d_loaded_source_refs_is_union` — `from ledger_kit.detectors import loaded_source_refs`.
  - `test_cr_lc_3e_money_helpers` — `percent_of(Decimal("100.00"), Decimal("21")) == Decimal("21.00")`, `within_tolerance`, `net_total`.
  - `test_cr_lc_3f_empty_ledger_context_detector_runs` — a local detector that reads `context["payments"]` alerts for `pd.DataFrame()` through `run_all`.
  - `test_cr_lc_3g_mask_iban_and_row_columns` — `mask_iban("ES88 2100 0418 5602 0005 1332") == "****1332"`; `explain_with_meta` accepts `row_columns=`.
  - `test_fill_fallback_is_public` — `from ledger_kit.explainer import fill_fallback` works and fills `{total:money}`; `ledger_kit.explainer` has no `_fill_fallback` attribute (DN-9).
- [x] No implementation: this task only fails if a ledger-core task is missing. If it fails, finish the named ledger-core task; never patch `ledger_kit/` from this spec.
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_ledger_core_contract.py -q` passes.

---

## Task P3 — Typed readers and identifier keys

**Covers**: REQ-PI-06, REQ-PI-07, REQ-PI-08, §4.1–§4.3

- [x] Write `tests/test_pi_utils_keys.py`:
  - **Tier 1**: `test_n1_n2_table_of_req_pi_07` — the six rows of the REQ-PI-07 table (`F-2026-0042`, `F2026-042`, `f-2026-0042`, `ALQ-2026-01`, `ALQ-2026-02`, `F-000`); `test_tax_key_and_name_key_examples` (`b-00000001` → `B00000001`; `Suministros García, S.L.` → `SUMINISTROSGARCIASL`); `test_iban_key_removes_all_whitespace_and_keeps_hyphens`.
  - **Tier 1**: `test_as_text_as_decimal_as_date_as_bool_typical` — a `Decimal`, a `date`, a `pd.Timestamp` (→ date), the bool `True` / `np.True_`.
  - **Tier 2**: `test_is_missing_every_kind` — `None`, `NaN`, `pd.NA`, `pd.NaT`, `Decimal("NaN")`, `""`, `" "`, `"\u00a0"`, `"-"`, `"–"`, `"—"`, `"--"`; `test_as_decimal_rejects_float_int_and_string`; `test_as_text_keeps_value_unstripped`; `test_as_date_rejects_string`; `test_as_bool_false_for_everything_else`; `test_n1_empty_for_symbols_only` (`"/ /"` → `""`); `test_equal_n1_does_not_imply_equal_n2` (`F0-05` / `F005`); `test_n2_all_zero_run_becomes_zero`.
  - **Tier 3** (`max_examples=200`): `test_dirty_cells_never_raise_helpers` — every helper and every key function on `dirty_cell()` values (text, `None`, `NaN`, floats, `Decimal` incl. NaN/inf, ints, dates) never raises; `test_n1_idempotent_and_alnum_only`; `test_n2_never_longer_than_n1`.
- [x] Implement in `detectors/utils.py`: `ZERO`, `DASH_CHARS`, `is_missing`, `as_text`, `as_decimal`, `as_date`, `as_bool`, `n1_key`, `n2_key`, `tax_key`, `name_key`, `iban_key` exactly as §4.1–§4.3.
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_utils_keys.py -q` passes; `ruff check` clean.

---

## Task P4 — IBAN validity

**Covers**: REQ-PI-23, OD-PI-15, §4.5

- [x] Write `tests/test_pi_utils_iban.py` using test-local checkers in `tests/pi_checkers.py` (mod-97, Spanish national check digits, NIF letter, CIF control character; the app and `ledger_kit` never validate tax ids). First fixture IBANs are literals:
  - **Tier 1**: `test_documented_iban_is_valid` — `iban_problem(iban_key("ES88 2100 0418 5602 0005 1332")) is None`; `test_checkers_agree_with_documented_example` — mod-97 remainder is 1 and the correct national digits are `45` while the IBAN carries `56` (REQ-PI-58); `test_format_problem_for_hyphens_dots_and_short_values`; `test_checksum_problem_for_valid_shape_bad_digits` (change `88` to `89`).
  - **Tier 2**: `test_is_valid_iban_matches_problem_none`; `test_lowercase_after_iban_key_is_valid`; `test_empty_key_is_format_problem`; `test_other_country_valid_iban_accepted` (national digits and per-country lengths are not validated, OD-PI-15); `test_constants_values` (`IBAN_MOD97_MODULUS == 97`, `IBAN_MOD97_REMAINDER == 1`).
  - **Tier 3** (`max_examples=200`): `test_iban_problem_never_raises_on_any_text`; `test_valid_iban_stays_valid_when_spaced_and_recased` (uses `iban_key`).
- [x] Implement in `detectors/utils.py`: `IBAN_FORMAT_RE`, `IBAN_MOD97_MODULUS`, `IBAN_MOD97_REMAINDER`, `iban_problem`, `is_valid_iban`. Create `tests/pi_checkers.py`.
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_utils_iban.py -q` passes; `ruff check` clean.

---

## Task P5 — Deterministic order, `load_rows`, `as_of`, alert hygiene

**Covers**: REQ-PI-10, REQ-PI-11, REQ-PI-12, REQ-PI-13, REQ-PI-65, DN-5, DN-7, §5

- [x] Write `tests/test_pi_utils_order.py`:
  - **Tier 1**: `test_source_ref_key_natural_order` — `f.csv:9` < `f.csv:10`, and plain text order would reverse them; `test_sort_refs_dedupes`; `test_load_rows_sorted_by_date_then_ref`; `test_resolve_as_of_explicit_wins`; `test_resolve_as_of_latest_over_invoices_and_all_payments` (credits included); `test_text_or_ref_and_supplier_label_fallbacks` (name → tax id as written → source_ref).
  - **Tier 1**: `test_finish_orders_by_first_ref_variant_id`.
  - **Tier 2**: `test_load_rows_empty_non_frame_and_missing_column` — `pd.DataFrame()`, `None`, a frame without `source_ref` → `[]`; `test_load_rows_drops_row_without_source_ref`; `test_load_rows_keeps_first_of_duplicate_source_ref`; `test_load_rows_missing_date_sorts_last`; `test_load_rows_conflicting_duplicates_are_shuffle_invariant` (DN-5); `test_source_ref_key_non_integer_row` → `(ref, -1)`; `test_resolve_as_of_none_without_any_date`; `test_resolve_as_of_ignores_unusable_dates`; `test_resolve_as_of_never_calls_the_clock` — `monkeypatch` makes `date.today` and `datetime.now` raise.
  - **Tier 3** (`max_examples=200`): `test_load_rows_shuffle_invariant`; `test_load_rows_one_row_per_source_ref`; `test_sort_refs_is_sorted_and_distinct`.
- [x] Implement in `detectors/utils.py`: `source_ref_key`, `sort_refs`, `_tiebreak`, `load_rows`, `_column`, `resolve_as_of`, `text_or_ref`, `supplier_label`, `finish`.
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_utils_order.py -q` passes; `ruff check` clean.

---

## Task P6 — Supplier master and payment attribution

**Covers**: REQ-PI-09, REQ-PI-25, DN-12, §4.4

- [ ] Write `tests/test_pi_utils_master.py`:
  - **Tier 1**: `test_build_master_indexes_by_tax_name_and_iban`; `test_attribute_payment_by_name`; `test_attribute_payment_by_iban_when_name_unknown`; `test_attribute_payment_name_first_even_if_iban_differs` (OD-PI-09: a payment to a known supplier sent to another account is still attributed).
  - **Tier 2**: `test_duplicate_tax_key_first_in_source_ref_order_wins`; `test_master_row_with_empty_tax_key_is_not_a_supplier` (DN-12); `test_name_hit_on_two_suppliers_falls_through_to_iban`; `test_iban_hit_on_two_suppliers_is_unattributed`; `test_unknown_name_and_unknown_iban_returns_none`; `test_build_master_empty_none_and_non_frame`; `test_attribute_payment_missing_cells`.
  - **Tier 3** (`max_examples=200`): `test_attribution_independent_of_master_row_order_when_unambiguous`; `test_attribute_payment_never_raises_on_dirty_cells`.
- [ ] Implement in `detectors/utils.py`: `Master`, `build_master`, `attribute_payment`.
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_utils_master.py -q` passes; `ruff check` clean.

---

## Task P7 — Multi-rate quarantine

**Covers**: REQ-PI-15, OD-PI-08, §6

- [ ] Write `tests/test_pi_prepare.py`:
  - **Tier 1**: `test_multi_rate_group_removed_and_recorded` — two rows, same supplier and `N1`, rates 21 and 10 → both removed, two records with `reason == "multi_rate_invoice_out_of_scope"` and the keys `source_file`, `source_row`, `reason`, `raw`, in natural `source_ref` order; `test_clean_invoices_untouched`.
  - **Tier 2**: `test_missing_rate_not_counted_as_different_rate`; `test_rate_21_and_21_00_are_one_rate`; `test_same_number_other_supplier_not_grouped`; `test_empty_frame_and_non_frame_return_unchanged`; `test_input_frame_not_mutated`; `test_clean_frame_has_fresh_range_index`; `test_raw_values_are_strings_and_missing_is_empty`.
  - **Tier 3** (`max_examples=200`): `test_quarantine_partitions_rows` — clean + quarantined row counts equal the input, source_refs disjoint.
- [ ] Implement `apps/phantom_invoices/prepare.py` (`MULTI_RATE_REASON`, `quarantine_multi_rate`).
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_prepare.py -q` passes; `ruff check` clean.

---

## Task P8 — Identifier generators (IBAN and tax ids)

**Covers**: REQ-PI-58, REQ-PI-70 (checker half), Finance Rule 5, §15.3

- [ ] Write `tests/test_pi_identifiers.py`. It loads `scripts/generate_samples.py` by path with `importlib.util.spec_from_file_location` (`scripts/` is not a package) in a module-level helper:
  - **Tier 1**: `test_correct_national_dc_example` — `correct_national_dc("2100", "0418", "0200051332") == "45"`; `test_wrong_national_dc_example` — `"56"`; `test_make_iban_reproduces_documented_example` — `format_iban(make_iban("2100", "0418", "0200051332")) == "ES88 2100 0418 5602 0005 1332"`; `test_make_cif_and_make_nif_examples` (control character always wrong for `k = 1…25`; the checkers of `pi_checkers.py` confirm).
  - **Tier 2**: `test_every_generated_iban_is_mod97_valid_with_wrong_national_digits` for `k = 1…25` and `k = 101…110`; `test_tax_ids_distinct_for_k_1_to_25`; `test_make_nif_skips_multiples_of_23` (`k = 12` → number 1013) and never yields `00000000T`; `test_wrong_dc_never_equals_correct_dc` for 200 random bank/branch/account triples.
  - **Tier 3** (`max_examples=200`): `test_make_iban_valid_checksum_for_any_digits`; `test_make_iban_national_digits_never_correct`.
- [ ] Implement in `scripts/generate_samples.py` (extend the ledger-core Task 13 file; keep its existing modes untouched): `SPANISH_DC_WEIGHTS`, `_dc_digit`, `correct_national_dc`, `wrong_national_dc`, `iban_check_digits`, `make_iban`, `format_iban`, `NIF_LETTERS`, `cif_control_digit`, `make_cif`, `make_nif`, exactly as §15.3. Money is not computed here.
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_identifiers.py -q` passes; existing ledger-core sample tests still pass (`pytest tests -q`); `ruff check` clean.

---

## Task P9 — Shared fixtures and builders

**Covers**: REQ-PI-62, §16.1, §16.3

- [ ] Write `tests/test_pi_fixtures.py` first (each fixture has the right shape):
  - `test_fixture_columns_match_canonical_columns` — invoice fixtures have `INVOICE_COLUMNS`, supplier fixtures `SUPPLIER_COLUMNS`, payment fixtures `CANONICAL_COLUMNS` (from `ledger_kit.ingestion.normaliser`).
  - `test_make_invoices_derives_vat_and_total_with_money_helpers` — defaults EUR, rate 21, `vat_amount = percent_of`, `total = net_total`, `source_ref == "inv.csv:{i}"`.
  - `test_fixture_identifiers_follow_finance_rule_5` — every IBAN is mod-97 valid with wrong national digits, every tax id has a wrong control character (via `pi_checkers`), emails only `@example.com`.
  - `test_clean_ledger_10_raises_no_alert_from_any_detector` — skipped via `pytest.importorskip` markers until Tasks P10–P13 exist; the final form runs `run_pi_detectors` (Task P14 re-enables it).
  - `test_single_row_and_empty_ledger_shapes`; `test_ctx_returns_mapping_proxy`.
- [ ] Implement `tests/conftest.py`: `make_invoices`, `make_suppliers`, `make_payments`, `ctx`, `make_test_iban` (loaded by path from `scripts/generate_samples.py`), strategies `dirty_cell`, `dirty_frame`, `valid_iban`, `spaced_cased`, `consecutive_numbers`, `reconciliation_inputs`, and the fixtures `empty_ledger`, `single_row_ledger`, `clean_ledger_10`, `suppliers_master`, `payments_for_clean`, `ledger_with_duplicate_invoice` (P1), `ledger_with_near_duplicate` (P3), `ledger_with_iban_change` (P5), `ledger_with_vat_error` (P7), `ledger_with_unpaid_invoice`, `ledger_with_double_payment` (P9). Dates are fixed literals.
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_fixtures.py -q` passes; `ruff check` clean.

---

## Task P10 — `pi.duplicate_invoice`

**Covers**: REQ-PI-16 to REQ-PI-21a, REQ-PI-63 (P1, P2, P3, P10), REQ-PI-64, REQ-PI-66, DN-1, DN-3, §7

- [ ] Write `tests/test_pi_duplicate_invoice.py`:
  - **Tier 1**: `test_duplicate_invoice_fires_on_typical_input`; `test_duplicate_invoice_silent_on_clean_ledger`; `test_pi_acceptance_p01_same_invoice_twice` (one `critical` `same_number`, and the other three detectors silent once Task P14 exists — here only this detector is asserted); `test_pi_acceptance_p02_monthly_rent_no_alert`; `test_pi_acceptance_p03_near_identical_numbers` (`warning`, `near_identical_number`, `days_apart 3`); `test_pi_acceptance_p10_same_total_6_7_8_days` (parametrised); `test_pi_same_number_2_days_apart_is_critical`; `test_pi_same_number_200_days_apart_no_alert`; `test_alert_title_and_data_contract` (every key of REQ-PI-20, `Alert.data` holds only `str`, `int`, `list[str]`); `test_through_run_all_namespace_pi`.
  - **Tier 2** (every row of §7.6 as a named test): `test_empty_n1_row_skipped`; `test_missing_number_date_or_total_skipped`; `test_non_string_number_skipped`; `test_identical_source_ref_uses_one_row`; `test_multi_rate_group_no_alert_second_line_of_defence` (REQ-PI-16); `test_same_number_different_suppliers_no_alert`; `test_rule_c_6_days_alerts_7_does_not`; `test_rule_a_179_days_alerts_180_does_not`; `test_totals_differing_by_one_cent_not_equal`; `test_different_currency_never_paired` (DN-1); `test_group_of_three_with_mixed_rules_gives_one_alert_of_top_rule` (REQ-PI-19); `test_consecutive_numbers_with_equal_totals_fire_rule_c` (documents OD-PI-06); `test_window_constants_ordered` (`DUPLICATE_WINDOW_DAYS <= SAME_NUMBER_WINDOW_DAYS`); `test_constants_values`; `test_empty_ledger_and_empty_dataframe_return_empty_list`; `test_single_row_returns_list`; `test_empty_context_mapping_proxy_does_not_raise`.
  - **Tier 3** (`max_examples=200`): `test_consecutive_numbers_with_different_totals_never_duplicate`; `test_row_order_never_changes_any_detector` (this detector); `test_source_refs_subset_of_loaded_inputs` (via `loaded_source_refs`); `test_detector_idempotent`; `test_dirty_cells_never_raise`; `test_empty_input_returns_empty`.
- [ ] Implement `detectors/duplicate_invoice.py` (`@register("pi.duplicate_invoice")`, `_Inv`, `_usable`, `_drop_multi_rate`, `_pair_variant`, `_groups`, `_alert`, constants).
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_duplicate_invoice.py -q` passes; `ruff check` clean.

---

## Task P11 — `pi.iban_change` (Poltergeist IBAN)

**Covers**: REQ-PI-22 to REQ-PI-28, REQ-PI-63 (P4, P5, P12), REQ-PI-64, §8

- [ ] Write `tests/test_pi_iban_change.py`:
  - **Tier 1**: `test_iban_change_fires_on_typical_input` (P5 fixture); `test_iban_change_silent_on_clean_ledger`; `test_pi_acceptance_p04_spaces_and_lowercase_no_alert`; `test_pi_acceptance_p05_new_valid_iban_critical` (`source_refs [inv.csv:0, sup.csv:0]`, masks `****2345`/`****1332`, `verification_message == VERIFY_BY_PHONE_MESSAGE`); `test_pi_acceptance_p12a_hyphenated_iban_warning_format`; `test_pi_acceptance_p12b_nan_iban_skipped`; `test_payment_to_non_master_iban_critical`; `test_verify_by_phone_message_has_no_digit`; `test_alert_data_contracts` for the three variants; `test_through_run_all_namespace_pi`.
  - **Tier 2** (every row of §8.4): `test_ibans_differing_before_last_four_still_alert_with_last4_identical`; `test_nbsp_inside_iban_removed`; `test_hyphen_only_iban_is_missing`; `test_checksum_failure_reason_checksum` (planted by the test only); `test_lowercase_accepted`; `test_invoice_and_payment_same_supplier_two_independent_alerts`; `test_empty_ledger_with_non_master_payment_alerts` (REQ-PI-22); `test_everything_empty_returns_empty_list`; `test_unknown_supplier_skipped`; `test_nan_and_none_ibans_skipped`; `test_invalid_master_iban_flagged_once_and_never_compared`; `test_attribution_by_name_and_by_iban_for_payments`; `test_credit_payments_ignored`; `test_one_alert_per_row`; `test_missing_suppliers_and_payments_keys_in_context`.
  - **Tier 3** (`max_examples=200`): `test_iban_spacing_and_case_never_fire`; `test_alert_data_never_contains_full_iban` (REQ-PII-04); `test_row_order_never_changes_any_detector`; `test_source_refs_subset_of_loaded_inputs` (ledger **and** suppliers **and** payments); `test_detector_idempotent`; `test_dirty_cells_never_raise`; `test_empty_input_returns_empty`.
- [ ] Implement `detectors/iban_change.py` (`@register("pi.iban_change")`, `VERIFY_BY_PHONE_MESSAGE`, `_iban_state`, `_valid_master_key`, `_invalid`, `_invoice_differs`, `_payment_differs`; re-export of the IBAN constants from `utils`).
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_iban_change.py -q` passes; `ruff check` clean.

---

## Task P12 — `pi.vat_error`

**Covers**: REQ-PI-29 to REQ-PI-33, REQ-PI-63 (P6, P7, P8, P11), REQ-PI-64, REQ-PI-66, OD-PI-16, §9

- [ ] Write `tests/test_pi_vat_error.py`:
  - **Tier 1**: `test_vat_error_fires_on_typical_input`; `test_vat_error_silent_on_clean_ledger`; `test_pi_acceptance_p06_correct_vat`; `test_pi_acceptance_p07_wrong_vat_consistent_total_one_alert` (`expected_vat_amount "21.00"`, `vat_amount "12.10"`); `test_pi_acceptance_p08_withholding`; `test_pi_acceptance_p11_surcharge`; `test_total_mismatch_alert_contract`; `test_vat_rate_not_allowed_contract` (`allowed_vat_rates == "21, 10, 4, 0"`); `test_through_run_all_namespace_pi`.
  - **Tier 2**: `test_vat_amount_boundary_0_01_clean_0_02_alerts`; `test_total_boundary_0_01_clean_0_02_alerts`; `test_rate_21_00_allowed_20_and_5_alert`; `test_rate_zero_with_zero_vat_clean`; `test_missing_base_rate_vat_or_total_skips_only_that_check`; `test_string_and_float_cells_treated_as_missing`; `test_half_up_case_0_50_at_21_percent` (stated `0.11` clean, `0.09` alerts); `test_withholding_larger_than_base_plus_vat_is_total_mismatch_not_error`; `test_missing_surcharge_and_withholding_default_to_zero`; `test_empty_ledger_and_empty_dataframe_return_empty_list`; `test_single_row_returns_list`; `test_constants_values`; `test_duplicate_source_ref_uses_first_row`.
  - **Tier 3** (`max_examples=200`): `test_correct_invoice_never_fires_vat_check`; `test_vat_off_by_two_cents_or_more_always_fires` (uses `assume` to keep the shifted VAT non-negative); `test_row_order_never_changes_any_detector`; `test_source_refs_subset_of_loaded_inputs`; `test_detector_idempotent`; `test_dirty_cells_never_raise`; `test_empty_input_returns_empty`.
- [ ] Implement `detectors/vat_error.py` (`@register("pi.vat_error")`, `VAT_TOLERANCE`, `TOTAL_TOLERANCE`, `ALLOWED_VAT_RATES`, `_m`, `_alert`). All money through `percent_of`, `net_total`, `within_tolerance`, `round_to_cents`; no arithmetic operator on a `Decimal` in this file (REQ-MON-03; the test scans the module with `ast` for `BinOp` on money names).
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_vat_error.py -q` passes; `ruff check` clean.

---

## Task P13 — `reconcile` and `pi.reconciliation`

**Covers**: REQ-PI-34 to REQ-PI-40, REQ-PI-63 (P9), REQ-PI-64, REQ-PI-66, OD-PI-11, OD-PI-17, DN-6, §10

- [ ] Write `tests/test_pi_reconciliation.py`:
  - **Tier 1**: `test_reconciliation_fires_on_typical_input` (overdue invoice); `test_reconciliation_silent_on_clean_ledger` (`clean_ledger_10` + `payments_for_clean`); `test_pi_acceptance_p09_invoice_paid_twice` (invoice and `pay.csv:0` `matched`, `pay.csv:1` `unmatched`, one `payment_without_invoice` with `source_refs [pay.csv:1, sup.csv:0]`, no `invoice_overdue`); `test_overdue_alert_contract` (`days_past_due`, `due_date_is_default`); `test_open_not_due_is_silent`; `test_reconcile_returns_all_four_fields` (`invoice_buckets`, `payment_buckets`, `matches`, `payment_supplier`); `test_through_run_all_namespace_pi`.
  - **Tier 2** (every row of §10.6): `test_payment_on_issue_date_and_on_due_plus_60_matches_one_day_outside_does_not`; `test_due_plus_15_open_due_plus_16_overdue`; `test_amount_difference_0_01_matches_0_02_does_not`; `test_different_currency_does_not_match`; `test_two_equal_invoices_two_payments_pair_in_date_ref_order`; `test_credits_ignored`; `test_payment_attributed_by_name_and_by_iban`; `test_unknown_counterparty_and_iban_is_in_no_bucket`; `test_as_of_none_no_overdue_alert`; `test_invoice_of_supplier_not_in_master_never_matched` (OD-PI-11); `test_defaulted_due_date_flagged`; `test_duplicate_source_ref_uses_first_row`; `test_unusable_rows_in_no_bucket_and_never_raise`; `test_partial_payment_overpayment_and_payment_before_issue_not_matched` (OD-PI-17); `test_empty_ledger_with_unmatched_supplier_payment_alerts`; `test_everything_empty_returns_empty_list`; `test_constants_values`.
  - **Tier 3** (`max_examples=200`, strategy `reconciliation_inputs`): `test_every_invoice_and_supplier_payment_in_exactly_one_bucket` (keys equal the usable invoices and supplier payments; `matches` one-to-one); `test_row_order_never_changes_any_detector`; `test_source_refs_subset_of_loaded_inputs`; `test_detector_idempotent`; `test_dirty_cells_never_raise`; `test_empty_input_returns_empty`.
- [ ] Implement in `detectors/utils.py`: `PAYMENT_MATCH_WINDOW_DAYS`, `UNPAID_GRACE_DAYS`, `MATCH_AMOUNT_TOLERANCE`, `InvoiceView`, `PaymentView`, `invoice_view`, `payment_view`, `Reconciliation`, `reconcile`. Implement `detectors/reconciliation.py` (`@register("pi.reconciliation")`, constants re-exported).
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_reconciliation.py -q` passes; `ruff check` clean.

---

## Task P14 — Registration and `run_pi_detectors`

**Covers**: REQ-PI-02, REQ-PI-14, REQ-PI-61, OD-PI-04, §1.1

- [ ] Write `tests/test_pi_registry.py` (use the ledger-core `_snapshot_registry` / `_restore_registry` fixtures; no `_clear_registry`):
  - `test_auto_discover_registers_four_pi_detectors` — exactly `pi.duplicate_invoice`, `pi.iban_change`, `pi.reconciliation`, `pi.vat_error` in `registered_names(namespace="pi")`.
  - `test_labels_cover_every_registered_pi_detector` — `LABELS` keys equal the registered names; `LABELS["pi.iban_change"] == "Poltergeist IBAN"`.
  - `test_run_pi_detectors_empty_everything_returns_empty_alerts` — four `DetectorResult`s, each with `alerts == []` and no error.
  - `test_run_all_passes_context_as_mapping_proxy_and_detectors_do_not_mutate_it` — frames in the context are equal before and after.
  - `test_detectors_accept_empty_mapping_proxy_context` — each of the four, `MappingProxyType({})`.
  - `test_no_zs_detector_runs_in_pi_namespace`.
  - `test_clean_ledger_10_raises_no_alert_from_any_detector` — the placeholder of Task P9 now runs without skipping.
  - `test_pi_acceptance_p01_no_other_detector_fires` — P1 through `run_pi_detectors`: exactly one alert in total, `critical`.
- [ ] Implement `detectors/__init__.py` (`LABELS`, `auto_discover("apps.phantom_invoices.detectors")`, `run_pi_detectors`) exactly as §1.1. Remove the skip from the Task P9 test.
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_registry.py apps/phantom_invoices/tests/test_pi_fixtures.py -q` passes; `ruff check` clean.

---

## Task P15 — Explanation support

**Covers**: REQ-PI-41 to REQ-PI-47, REQ-PI-68, REQ-PI-26, DN-8, DN-9, §12

- [ ] Write `tests/test_pi_explain_support.py` (all with the ledger-core `MockLLMClient`; no network):
  - **Tier 1**: `test_templates_cover_every_variant` — `TEMPLATES` has exactly the 11 `(detector, variant)` keys of §12.4; `test_every_template_fills_from_a_real_alert` — build one real alert per variant (fixtures P1, P3, same-total, P5, non-master payment, invalid IBAN, P7, a `total_mismatch`, a bad rate, overdue, P9), fill with `fill_fallback` **imported from `ledger_kit.explainer`**: no `{` or `}` left, amounts in European format, a cited `source_ref` present; `test_row_columns_reach_the_client` — `client.calls[0]["messages"]` contains no `iban`, `supplier_tax_id`, `tax_id`, `id` or `description` key; `test_guard_accepts_a_sentence_restating_only_alert_data` for each variant; `test_build_explain_rows_takes_rows_from_all_three_frames` (payment rows contribute only `currency`/`source_ref`, master rows only `supplier_name`/`source_ref`).
  - **Tier 1**: `test_hallucinating_stub_is_rejected_by_number_guard` — `explain_with_meta(alert, rows, fallback_template=..., client=HallucinatingStubClient(fill_fallback(...)), row_columns=ROW_COLUMNS)` → `source == "fallback"`, `rejected_numbers == ("99999.99",)`; `test_guard_badge_three_plus_one_texts` (llm, no key, rejected, key present with error: "Template (LLM unavailable)", DN-8); `test_stub_shape_matches_mock_client` (`chat` and `completions` are properties; `create` returns `choices[0].message.content`).
  - **Tier 2**: `test_guard_rejects_hallucinated_amount`; `test_guard_rejects_uncited_date`; `test_guard_rejects_iban_shaped_token`; `test_no_api_key_returns_fallback_without_network` (REQ-PI-44); `test_template_for_unknown_variant_raises_keyerror_with_clear_message`; `test_build_explain_rows_empty_and_non_frame_inputs`; `test_templates_recommend_no_action` (no "should", "cancel", "refuse", "pay"); `test_allowed_vat_rates_string_tokenises_as_four_numbers`; `test_injected_number_not_in_any_alert`.
  - **Tier 3** (`max_examples=200`): `test_guard_accepts_any_alert_data_sentence`.
- [ ] Implement `apps/phantom_invoices/explain_support.py`: `ROW_COLUMNS`, `TEMPLATES`, `template_for`, `build_explain_rows`, `explain_alert`, `guard_badge`, `HallucinatingStubClient`. It calls `fill_fallback` from `ledger_kit.explainer` where it needs a filled template and defines no wrapper.
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_explain_support.py apps/phantom_invoices/tests/test_pi_scaffold.py -q` passes (the scaffold test confirms no private import); `ruff check` clean.

---

## Task P16 — Flashlight renderer and theme

**Covers**: REQ-PI-48, REQ-PI-50 (renderer half), §13.1, §13.3

- [ ] Write `tests/test_pi_flashlight.py`:
  - **Tier 1**: `test_cited_rows_lit_and_others_dimmed` — `class="lit"` for refs in `lit_refs`, `class="dim"` for the rest, table class `ledger has-lit`; `test_no_lit_refs_dims_nothing` — table class `ledger`, no `dim`; `test_header_cells_rendered`.
  - **Tier 2**: `test_script_tag_and_quotes_are_escaped` (`<script>alert(1)</script>`, `"`, `'`, `&` in any cell and in a column name); `test_missing_cells_render_empty` (`None`, `NaN`, `pd.NA`, `"-"` shown as empty); `test_empty_frame_renders_header_only`; `test_row_without_source_ref_column_is_dimmed_when_lit_refs_given`; `test_haunted_css_contains_theme_colours_and_dim_opacity` (`#12101a`, `#7cffb2`, `opacity: 0.25`, `box-shadow`, `radial-gradient`) and `test_haunted_css_has_no_external_url`.
  - **Tier 3** (`max_examples=200`): `test_render_never_emits_unescaped_markup` — for arbitrary text cells, the output contains no `<` other than the fixed tags of the template.
- [ ] Implement `apps/phantom_invoices/flashlight.py` (`HAUNTED_CSS`, `_esc`, `render_ledger_html`). Pure: no Streamlit import.
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_flashlight.py -q` passes; `ruff check` clean.

---

## Task P17 — Settings, `config.toml` and `run_pipeline`

**Covers**: REQ-PI-01, REQ-PI-02, REQ-PI-03, REQ-PI-04, REQ-PI-59, REQ-PI-60, §3, §14.1

- [ ] Write `tests/test_pi_settings.py`:
  - **Tier 1**: `test_load_config_reads_demo_paths`; `test_to_date_accepts_string_and_date`; `test_demo_inputs_reads_three_files_as_sources`; `test_run_pipeline_on_minimal_fixtures` — bytes of small CSVs for the three inputs give a `Pipeline` with clean invoices, suppliers, payments, `as_of_used`, four `DetectorResult`s and a `Reconciliation`; `test_config_has_only_demo_section_and_no_threshold_names` (REQ-PI-59: none of `DUPLICATE_WINDOW_DAYS`, `SAME_NUMBER_WINDOW_DAYS`, `VAT_TOLERANCE`, `TOTAL_TOLERANCE`, `ALLOWED_VAT_RATES`, `PAYMENT_MATCH_WINDOW_DAYS`, `UNPAID_GRACE_DAYS`, `MATCH_AMOUNT_TOLERANCE`, `DUPLICATE_TOTAL_TOLERANCE` appears).
  - **Tier 2**: `test_missing_files_are_empty_inputs_with_canonical_columns` (REQ-ING-28); `test_json_invoices_routed_to_json_reader`; `test_multi_rate_rows_in_quarantine_tagged_with_file_kind`; `test_quarantine_records_keep_ledger_core_shape`; `test_explicit_as_of_wins_over_data`; `test_as_of_used_is_none_without_any_date`; `test_pipeline_does_not_read_the_clock`; `test_credits_in_payments_are_passed_through_not_filtered` (REQ-PI-03).
  - **Tier 3**: `test_run_pipeline_shuffled_rows_same_alerts` for a small generated invoices CSV.
- [ ] Create `apps/phantom_invoices/config.toml` (`[demo]` three paths, `as_of` commented out; no thresholds, no secrets). Implement `settings.py` (`Source`, `Pipeline`, `DemoInputs`, `load_config`, `to_date`, `demo_inputs`, `_tag`, `run_pipeline`). Money is not computed here.
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_settings.py -q` passes; `ruff check` clean.

---

## Task P18 — Demo generator: suppliers, clean invoices, payments

**Covers**: REQ-PI-54, REQ-PI-55, REQ-PI-56, REQ-PI-58, REQ-PI-70 (part), §15.1–§15.3, §15.5 (clean suppliers)

- [ ] Write `tests/test_pi_demo_generator.py` (the generator module is loaded by path):
  - `test_build_phantom_demo_is_deterministic` — two calls with seed 42 give identical strings; a different seed changes only the clean-supplier rows (planted rows and tax ids are seed-independent).
  - `test_files_are_plain_dialect_with_documented_columns` — headers equal §15.2; comma separator, dot decimal, ISO dates; no BOM; `\n` line endings.
  - `test_twenty_five_suppliers_sixteen_cases_nine_clean` — `PHANTOM_CASES` has the 16 keys of §15.3; `CLEAN_SUPPLIERS` has 9 tax ids; 20–26 suppliers.
  - `test_every_iban_valid_mod97_with_wrong_national_digits` and `test_every_tax_id_has_wrong_control_character_all_distinct` over all three files (REQ-PI-58, via `pi_checkers`); `test_no_email_or_phone_in_any_file`.
  - `test_clean_suppliers_have_five_monthly_invoices_with_distinct_totals`; `test_clean_invoice_amounts_built_with_money_helpers` (vat equals `percent_of(base, rate)`, total equals `net_total`).
  - `test_every_clean_invoice_paid_by_exact_total_inside_window_to_master_iban`; `test_latest_date_in_data_is_demo_latest_date` (`2026-10-30`, a clean payment of `C9`); `test_payments_sorted_by_date_counterparty_amount`; `test_payments_have_three_credits_and_four_unrelated_debits`.
  - `test_generator_uses_only_random_random_with_seed` — `ast` scan: no module-level `random.` call, no `datetime.now`/`today`.
- [ ] Implement in `scripts/generate_samples.py`: `PHANTOM_CASES`, `CLEAN_SUPPLIERS`, `DEMO_LATEST_DATE`, `BANKS`, supplier plan table, `build_phantom_demo(seed=42)` producing suppliers, the nine clean suppliers' invoices and payments (planted rows are added in Task P19), `write_phantom_demo(out_dir, seed)`, and the CLI `--mode phantom-demo --seed N`. Uses `random.Random(seed)` consumed in fixed order, `csv.writer(lineterminator="\n")`, UTF-8 without BOM.
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_demo_generator.py -q` passes; `ruff check` clean.

---

## Task P19 — Demo generator: planted cases

**Covers**: REQ-PI-57 (P1–P12 and plants a–e), REQ-PI-56 (size), §15.4, §15.5, §15.6

- [ ] Extend `tests/test_pi_demo_generator.py` first:
  - `test_demo_sizes` — 70 invoice rows (25 planted + 45 clean), 25 suppliers, 62 payment rows.
  - `test_each_phantom_case_has_a_dedicated_supplier_tax_id` — the 16 `PHANTOM_CASES` values are distinct and appear in `suppliers.csv`.
  - One test per planted case checking its rows against §15.4/§15.5 literally (numbers, issue and due dates, base/rate/VAT/total, payments, IBAN spelling): `test_planted_p1` … `test_planted_p12`, `test_planted_non_master_payment`, `test_planted_overdue`, `test_planted_open_not_due`, `test_planted_multi_rate`, `test_clean_invoices_without_due_date` (those with `(j + m) % 4 == 0`).
  - `test_p12_hyphenated_iban_derived_from_supplier_valid_iban` and `test_p4_invoice_iban_lowercase_with_spaces`.
  - `test_no_planted_invoice_besides_the_overdue_one_is_past_its_grace_period` (`issue + 30 + 15 >= 2026-10-30` unless paid).
  - `test_two_thirds_of_invoices_are_clean`.
- [ ] Extend `build_phantom_demo` with the 16 literal planted cases; the planted rows use no randomness. Amounts are built from strings and `percent_of` / `net_total` only.
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_demo_generator.py -q` passes; `ruff check` clean.

---

## Task P20 — `.gitattributes` line for the demo CSVs

**Covers**: DN-10, REQ-PI-54 (byte-identical output on Windows), §1, §15.1

- [ ] Write `tests/test_pi_gitattributes.py`:
  - `test_gitattributes_marks_phantom_demo_csvs_binary_like` — `.gitattributes` at the repository root contains the line `data/samples/phantom_demo/*.csv -text`.
  - `test_git_reports_text_unset_for_each_demo_csv` — `subprocess.run(["git", "check-attr", "text", "--", path])` for `suppliers.csv`, `invoices.csv`, `payments.csv` prints `text: unset`; skipped with a reason when `git` is not on `PATH` or the folder is not a repository.
  - `test_gitattributes_does_not_touch_other_patterns` — the file holds no `* text=auto` rule that would override the line (the `-text` line is the more specific, later-or-equal rule).
- [ ] Create or extend `.gitattributes` with `data/samples/phantom_demo/*.csv -text` (add a comment line above it: `# demo CSVs are byte-compared with the generator output; no autocrlf on Windows (DN-10)`). Do not remove existing lines.
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_gitattributes.py -q` passes.

---

## Task P21 — Generate and commit the demo files

**Covers**: REQ-PI-54, REQ-PI-55, REQ-PI-58, REQ-PI-70, Finance Rule 6, §15

- [ ] Extend `tests/test_pi_demo_data.py` (written before the files exist, so it fails first):
  - `test_committed_files_equal_generator_output` — each of `data/samples/phantom_demo/{suppliers,invoices,payments}.csv` read as **bytes** equals `build_phantom_demo(42)[name].encode("utf-8")`.
  - `test_committed_files_have_lf_line_endings_and_no_bom`.
  - `test_regenerating_into_tmp_path_twice_is_byte_identical` (`write_phantom_demo`).
  - `test_committed_files_parse_with_ledger_core_readers_and_zero_quarantine_except_multi_rate` — `parse_invoice`, `parse_suppliers`, `parse_csv` ingest them; the only quarantine is the two multi-rate rows after `quarantine_multi_rate`.
  - `test_identifier_rules_on_committed_files` (REQ-PI-70: mod-97 valid with wrong national digits; wrong tax-id control characters, all distinct; no e-mail or phone).
  - `test_gitignore_still_allows_data_samples_phantom_demo` — `git check-ignore` reports the three files as not ignored (skipped without git).
- [ ] Run `python scripts/generate_samples.py --mode phantom-demo --seed 42` to write `data/samples/phantom_demo/{suppliers,invoices,payments}.csv`; add the generation command and a "synthetic, no real data" note for this folder to `data/samples/README.md`.
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_demo_data.py -q` passes; `git status` shows the three CSVs as new files with no CRLF conversion warning.

---

## Task P22 — Streamlit app

**Covers**: REQ-PI-04, REQ-PI-46, REQ-PI-47, REQ-PI-49, REQ-PI-50, REQ-PI-51, REQ-PI-52, REQ-PI-53, DN-11, §13, §14.2

- [ ] Write `tests/test_pi_app_logic.py` for everything that needs no live browser:
  - `test_app_py_first_lines_bootstrap_sys_path` — the path bootstrap precedes the first `ledger_kit` import (`ast`).
  - `test_app_uses_on_click_for_load_demo` — `st.sidebar.button("Load demo data", on_click=load_demo)`; no `st.session_state[<widget key>] = ...` under an `if st.button(...)` body.
  - `test_ui_default_as_of_is_only_a_widget_seed` — `UI_DEFAULT_AS_OF == date(2026, 1, 1)`; it is passed to no detector unless `use_as_of` is true (DN-11).
  - `test_all_amounts_in_ledger_view_use_format_amount_and_iban_masked_and_no_tax_id_column`.
  - `test_status_column_icons` — ✅ matched, 🕯️ open_not_due, 💀 overdue, blank when the row is not usable.
  - `test_alerts_grouped_critical_then_warning`; `test_captions_for_last4_identical_and_default_due_date`; `test_verification_message_shown_only_for_the_two_critical_iban_variants`.
  - `test_explanation_cache_key_is_alert_id_and_client_mode`.
  - `test_notice_states_which_checks_need_which_file` (REQ-PI-04).
  - `test_selected_alert_reset_when_not_in_options`.
  - **`AppTest`** (`streamlit.testing.v1.AppTest.from_file("apps/phantom_invoices/app.py")`): `test_app_starts_without_exception`; `test_load_demo_click_shows_all_four_detector_labels_without_widget_error` — click **Load demo data**, `at.exception` is empty (no `StreamlitWidgetAlreadyInstantiatedError`), the severity metrics read 3 and 6, labels of all four detectors are present; `test_hallucination_toggle_shows_warning_badge_with_99999_99` (REQ-PI-47); `test_selecting_an_alert_lights_only_its_source_refs`.
- [ ] Implement `apps/phantom_invoices/app.py`: path bootstrap; `load_demo` callback defined before the widgets and attached with `on_click`; sidebar uploaders (invoices `.csv`/`.json`, suppliers, payments), `use_as_of` checkbox and `as_of_date` input (seeded with `setdefault`), `hallucinate` toggle; SHA-256-keyed `pipeline_cache`; theme CSS via `st.markdown(..., unsafe_allow_html=True)`; severity metrics; haunted ledger via `render_ledger_html`; `st.radio(key="selected_alert")` flashlight; alert cards with `LABELS`, explanation (cached by `(alert.id, client_mode)`), `guard_badge`, `source_refs`, captions and the verbatim `verification_message`; cited master/payment tables; quarantine expander with the multi-rate limitation note; the `as_of` line. Pure view-model helpers go to `settings.py`/`explain_support.py` so the logic tests need no Streamlit runtime.
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_app_logic.py -q` passes; manual smoke test recorded in the PR: `streamlit run apps/phantom_invoices/app.py` starts; **Load demo data** shows the 9 alerts; `ruff check` clean.

---

## Task P23 — Update `.kiro/steering/structure.md` (phantom section)

**Covers**: REQ-PI-53 (supersedes per-app `requirements.txt`), requirements §12, OD-PI-14, design §1

- [ ] Write the check first, `tests/test_pi_structure_steering.py`: parse the layout tree of `.kiro/steering/structure.md` and assert that the `phantom_invoices/` block lists exactly the files below, contains no `requirements.txt`, and that every listed path exists on disk (`apps/phantom_invoices/...`, `data/samples/phantom_demo/*.csv`, `scripts/generate_samples.py`, `.gitattributes`).
- [ ] Replace the `apps/phantom_invoices/` block of the layout tree with the spec's file list:
  - App root: `__init__.py`, `app.py`, `config.toml`, `settings.py`, `prepare.py`, `explain_support.py`, `flashlight.py`; **remove `requirements.txt`**.
  - `detectors/`: `__init__.py`, `utils.py`, `duplicate_invoice.py`, `iban_change.py`, `vat_error.py`, `reconciliation.py`.
  - `tests/`: `conftest.py`, `pi_checkers.py`, and `test_pi_` modules: `scaffold`, `ledger_core_contract`, `utils_keys`, `utils_iban`, `utils_order`, `utils_master`, `prepare`, `identifiers`, `fixtures`, `duplicate_invoice`, `iban_change`, `vat_error`, `reconciliation`, `registry`, `explain_support`, `flashlight`, `settings`, `demo_generator`, `demo_data`, `gitattributes`, `app_logic`, `structure_steering`, `demo_e2e`.
  - Add, if absent: `scripts/generate_samples.py`, `.gitattributes`, `data/samples/phantom_demo/{suppliers,invoices,payments}.csv`, and the root `requirements.txt`.
  - Leave the `zombie_subscriptions/` block untouched (its own task, Z22, rewrites it).
- [ ] Add a one-line note under "Package boundaries": the phantom app may import `ledger_kit` (public names only) and its own `detectors/`, `settings.py`, `prepare.py`, `explain_support.py`, `flashlight.py`.
- [ ] Verify: `pytest apps/phantom_invoices/tests/test_pi_structure_steering.py -q` passes (the `test_pi_demo_e2e.py` entry is created by Task P24, so this check treats that single path as pending until then); no other section of the file changed.

---

## Task P24 — End-to-end demo and final integration check

**Covers**: REQ-PI-61 to REQ-PI-70, REQ-PI-12, REQ-PI-15, REQ-PI-57, §15.6, §16.4, §16.5

- [ ] Write `tests/test_pi_demo_e2e.py` (loads the committed `data/samples/phantom_demo/*.csv` through `run_pipeline`, the same path the app uses):
  - `test_demo_raises_exactly_nine_alerts_3_critical_6_warning` — total 9; `critical`: the P1 `same_number`, the P5 `invoice_iban_differs_from_master`, the `payment_to_non_master_iban`; `warning`: P3 `near_identical_number`, P10 `same_total_close_dates` (only `FAC-0101` + `FAC-0102`), P12 `iban_invalid` (only `TR-2026-014`), P7 `vat_amount_mismatch`, P9 `payment_without_invoice` (08-12 payment), the overdue `invoice_overdue` (`days_past_due == 41`).
  - `test_each_planted_case_raises_exactly_its_alerts_via_phantom_cases` — per `PHANTOM_CASES` supplier tax id, the alerts citing that supplier's rows equal the expectation of §15.4/§15.5; P2, P4, P6, P8, P11, `OPEN_NOT_DUE` have none.
  - `test_every_detector_fires_at_least_once` — all four `pi.*` names.
  - `test_multi_rate_rows_quarantined_and_raise_no_alert` — two records with `reason == "multi_rate_invoice_out_of_scope"`, no alert cites them, 68 invoices reach the detectors.
  - `test_no_alert_on_any_clean_supplier` — none of the nine `CLEAN_SUPPLIERS` tax ids is cited.
  - `test_as_of_defaults_to_latest_data_date` — `Pipeline.as_of_used == date(2026, 10, 30)`.
  - `test_every_source_ref_is_in_loaded_source_refs`; `test_no_alert_data_contains_a_full_iban`.
  - `test_every_alert_explanation_fallback_fills` — `explain_alert(..., client=None)` with no API key (`monkeypatch.delenv`) returns `source == "fallback"` for all 9 alerts, no leftover braces, a cited `source_ref`.
  - `test_hallucinating_stub_rejected_for_every_alert` — `rejected_numbers == ("99999.99",)` for all 9.
  - `test_result_identical_under_two_clocks` — `freeze_time("2020-01-01")` and `freeze_time("2031-12-31")` give equal alert lists (REQ-PI-65, §16.4 part 2).
  - `test_pipeline_result_independent_of_row_order` — the three files with shuffled data rows give the same 9 alerts.
- [ ] Fix `config.toml` / generator output until the test passes (the only legitimate fixes are in the demo data and `config.toml`; a failing detector is fixed in its own task's file with its test).
- [ ] Final checks:
  - `pytest apps/phantom_invoices/ --cov=apps/phantom_invoices --cov-fail-under=80`, then the full `pytest` to confirm ledger-core and zombie-subscriptions are unaffected.
  - Every acceptance example has a named test: `test_pi_acceptance_p01…p12` (P12 as p12a and p12b) and the two `REQ-PI-21a` tests.
  - All three tiers exist for each of the four detectors and for `reconcile`; all properties of REQ-PI-64 are present with `@settings(max_examples=200)`; every threshold constant is tested on both sides of its boundary (REQ-PI-66: 6/7, 179/180, 0.01/0.02 twice, 15/16, 60/61, 0.01/0.02).
  - No test or module reads the clock; `apps/phantom_invoices/requirements.txt` does not exist; no private `ledger_kit` name is imported by the app (`test_pi_scaffold.py`).
  - `ruff check .` and `ruff format --check .` pass with zero warnings.
  - The git working tree shows no CRLF warning for `data/samples/phantom_demo/` (DN-10).
- [ ] Fix any coverage gaps or lint issues found.
