# zombie-subscriptions — Implementation Tasks

**Depends on**: ledger-core Tasks 1–11a (scaffold, models, money, ingestion, normaliser, registry,
explainer). Nothing here modifies a file under `ledger_kit/`.

Every task is **test-first**: write the tests, watch them fail, implement until they pass, then run
`ruff check` and `ruff format --check`. Tasks are in dependency order. Property tests use
`@settings(max_examples=200)`; no test reads the system clock; fixtures use fictional merchants only.

Section references (§) point to `design.md`; REQ ids to `requirements.md`.

---

## Task Z1 — App package scaffold

**Covers**: REQ-ZS-41, §1, §8

- [x] Write `apps/zombie_subscriptions/tests/test_zs_scaffold.py`:
  - `test_app_package_importable` — `import apps.zombie_subscriptions` and `apps.zombie_subscriptions.detectors` succeed under plain `pytest`.
  - `test_no_app_level_requirements_txt` — `apps/zombie_subscriptions/requirements.txt` does not exist (it would hide the root file on Streamlit Community Cloud).
  - `test_app_does_not_import_other_app` — no module under the app imports `apps.phantom_invoices`; `ledger_kit` imports nothing from `apps`.
- [x] Create empty `apps/__init__.py`, `apps/zombie_subscriptions/__init__.py`, `apps/zombie_subscriptions/detectors/__init__.py`, `apps/zombie_subscriptions/tests/` (no `__init__.py` needed beyond what ledger-core Task 1 pytest config requires).
- [x] Verify: tests pass, `ruff check` clean.

---

## Task Z2 — Constants and counterparty normalisation

**Covers**: REQ-ZS-05, REQ-ZS-06, REQ-ZS-07, REQ-ZS-08 (constants), REQ-ZS-10, REQ-ZS-42, §2, §3

- [x] Write `tests/test_zs_utils_normalise.py` (in `apps/zombie_subscriptions/tests/`):
  - **Tier 1**: `test_normalise_examples` — `"Streamflix Intl."` → `"STREAMFLIX INTL"`, `"STREAMFLIX.COM"` → `"STREAMFLIXCOM"`, `"BEATSTREAM P2A3B4C5"` → `"BEATSTREAM"`.
  - **Tier 1**: `test_resolve_alias_hit_and_miss`, `test_normalise_alias_map_normalises_names_and_members`, `test_normalise_date_map_normalises_keys`.
  - **Tier 2**: `test_normalise_all_tokens_have_digits_falls_back`, `test_normalise_empty_string`, `test_resolve_alias_none_and_empty`, `test_normalise_alias_map_none`, `test_normalise_date_map_none`.
  - **Tier 3**: `test_normalise_idempotent`, `test_normalise_output_only_letters_and_spaces`, `test_normalise_case_and_whitespace_invariant`.
  - `test_constants_values` — every constant in design §2 exists with the stated value, including `STABLE_AMOUNT_RATIO == Decimal("0.02")`, `MAX_EDGE_STEP_RATIO == Decimal("0.50")`, `MIN_SIDE_ROWS == 2`; `INTERVAL_TYPES` order is weekly, monthly, quarterly, yearly; `INTERVALS_BY_NAME` matches.
  - `test_no_thresholds_in_config_toml` — once Z17 adds `config.toml`, it contains none of the constant names (REQ-ZS-42).
- [x] Implement the constants block, `INTERVAL_TYPES`, `INTERVALS_BY_NAME`, `normalise_counterparty`, `resolve_alias`, `normalise_alias_map`, `normalise_date_map` in `detectors/utils.py`.
- [x] Verify: tests pass, `ruff check` clean.

---

## Task Z3 — Ledger helpers

**Covers**: REQ-ZS-03 (debit-only input), REQ-ZS-13 (ordering of source_refs), REQ-ZS-13a, REQ-ZS-30, REQ-ZS-49, §3.1

- [x] Write `tests/test_zs_utils_helpers.py`:
  - **Tier 1**: `test_date_key_orders_by_date_then_source_row`; `test_sorted_source_refs_by_date_not_text` — refs `f.csv:9` and `f.csv:10` on consecutive dates come out `[f.csv:9, f.csv:10]`, and with the same date by `source_row`, never as text.
  - **Tier 1**: `test_group_by_normalised_key_groups_and_sorts` — keys alphabetical, rows by `date_key`; `test_group_by_canonical_collects_aliased_keys` — two aliased keys land under one canonical name, each with its own rows.
  - **Tier 1**: `test_ppy_for_all_interval_types`; `test_ledger_max_date`; `test_median_odd_even_decimal`.
  - **Tier 2**: `test_group_helpers_empty_ledger_return_empty`; `test_ledger_max_date_empty_returns_none`; `test_sorted_source_refs_dedupes_duplicate_source_ref`; `test_single_row_ledger_groups`.
  - **Tier 3**: `test_group_by_normalised_key_partitions_rows` — every input row appears in exactly one group.
- [x] Implement `date_key`, `sorted_source_refs`, `group_by_normalised_key`, `group_by_canonical`, `ppy_for`, `ledger_max_date`, `median` in `detectors/utils.py`.
- [x] Verify: tests pass, `ruff check` clean.

---

## Task Z4 — Shared fixtures

**Covers**: REQ-ZS-46, REQ-ZS-50, REQ-ZS-09 (E1–E7b input data), design §4.8, §11.1

- [x] Write `tests/test_zs_fixtures.py` first (each fixture has the right shape):
  - `test_fixture_columns_match_canonical_columns` — every fixture frame has `CANONICAL_COLUMNS` from `ledger_kit.ingestion.normaliser`.
  - `test_fixtures_are_debit_only_with_unique_source_refs`.
  - `test_fixture_counterparties_are_fictional_merchants` — all fixture counterparties come from a fixed allow-list (`CLOUDVAULT`, `STREAMFLEX INTL`, `MUSICBOX`, `STREAMFLIX INTL`, `STREAMFLIXCOM`, `SECUREPASS`, `GYMPLUS`, `FRESHCO`, `GLOWBILL`, `SUPERMART`, …); none is a person name, none is Spotify/Adobe/Dropbox/Netflix.
  - `test_weekly_shopping_fixture_matches_spec` — 26 rows, dates `2026-05-04 + 7·i`, amounts `round_to_cents(40.00 × 1.11^k)` with `k = (5·i) mod 13`; 13 distinct amounts, each exactly twice, 91 days apart, adjacent levels more than 10% apart.
- [x] Implement `apps/zombie_subscriptions/tests/conftest.py`: the `_debit_row` helper (explicit dates, no clock), builders for monthly/weekly rows, and the fixtures `empty_ledger`, `single_row_ledger`, `clean_ledger_10`, `ledger_with_recurring`, `ledger_with_price_increase`, `ledger_with_duplicate_sub`, `ledger_with_aliased_duplicate`, `ledger_with_free_trial`, `ledger_with_post_cancellation`, `ledger_with_zombie`, `ledger_with_weekly_shopping`, plus builder functions for the E2, E3, E6, E7 and downgrade series (design §4.8).
- [x] Verify: tests pass, `ruff check` clean.

---

## Task Z5 — Price buckets and cadence runs

**Covers**: REQ-ZS-08, REQ-ZS-09, §4.4, §4.5

- [x] Write `tests/test_zs_series_primitives.py`:
  - **Tier 1**: `test_group_by_price_level_splits_on_10pct` — 9.99 and 12.99 separate; 12.99 and 13.79 together.
  - **Tier 1**: `test_group_by_price_level_buckets_are_date_sorted` — a bucket built from amounts in non-date order comes back ordered by `date_key` (regression: buckets were returned sorted by amount).
  - **Tier 1**: `test_longest_cadence_run_skips_interleaved_rows` — E4 dates `Jan-01, Jan-15, Feb-01, Feb-15, Mar-01, Mar-15` → run `[Jan-01, Feb-01, Mar-01]` (length 3, no stride-2 step needed).
  - **Tier 1**: `test_longest_cadence_run_per_interval` — weekly 7±3, monthly 30±3, quarterly 91±3, yearly 365±3.
  - **Tier 2**: `test_longest_cadence_run_empty_and_single_row`; `test_gap_boundaries_inclusive` — gaps 27 and 33 accepted, 26 and 34 rejected; `test_group_by_price_level_empty`; `test_duplicate_source_ref_rows_do_not_crash`.
  - **Tier 3**: `test_buckets_partition_rows`; `test_run_is_subsequence_with_valid_gaps`; `test_bucket_membership_independent_of_input_order`.
- [x] Implement `group_by_price_level` (buckets returned sorted by `date_key`) and `longest_cadence_run`.
- [x] Verify: tests pass, `ruff check` clean.

---

## Task Z6 — `_segment_by_price`

**Covers**: REQ-ZS-09, REQ-ZS-10a, REQ-ZS-14, §4.3

- [x] Write `tests/test_zs_segment_by_price.py` (table-driven, runs built from amount lists):
  - **Tier 1 — Branch 1**: `test_stable_run_is_one_series_no_steps` (12.99 × 5); `test_two_percent_boundary` — amounts exactly 2% from the median are a level, just above are not.
  - **Tier 1 — Branch 2**: `test_step_up_recorded` (3 × 9.99 + 3 × 12.99 → `(9.99, 12.99)`, `current_amount=12.99`); `test_step_down_recorded` (14.99 → 9.99); `test_step_between_5_and_10_pct_is_recorded` — 12.99 × 3 then 13.79 × 3 (+6.2%) records a step (regression: it fell in one 10% bucket and was never recorded); `test_final_single_row_after_enough_rows_is_step` (12.99 × 5 + 15.99 → E1); `test_first_single_row_before_enough_rows_is_step` (12.99 + 15.99 × 5).
  - **Tier 1 — shopping guards**: `test_stray_low_amount_is_not_a_new_price` — 12.99 × 4 + 4.99 → `None`; `test_single_row_side_needs_interval_minimum` — monthly 12.99 × 2 + 15.99 → `None`; `test_trial_amount_before_series_is_not_a_step` — 0.49 + 14.99 × 3 → `None`; `test_two_row_run_must_be_one_level` — `[10.00, 10.90]` → `None`, `[10.00, 10.10]` → series; `test_one_row_each_side_not_a_step`; `test_edge_step_beyond_50pct_rejected` (+50% accepted, +51% rejected); `test_two_valid_splits_is_ambiguous_falls_to_branch3`.
  - **Tier 1 — Branch 3**: `test_variable_bill_within_10pct_uses_median` — amounts ±4% around 50.00, no step → `current_amount` = rounded median, `price_steps == []`; `test_amounts_beyond_10pct_of_median_rejected` (E7 amounts → `None`).
  - **Tier 2**: `test_step_ratio_uses_rounded_medians`; `test_equal_rounded_medians_not_a_step`; `test_run_of_one_row`; `test_current_amount_rounded_half_up`.
  - **Tier 3**: `test_noise_within_half_percent_of_one_level_is_stable` (never a step); `test_segment_result_rows_equal_input_rows`; `test_current_amount_is_median_of_last_level`.
- [x] Implement `is_level`, `_segment_by_price`, the `Series` dataclass in `detectors/utils.py` (steps stored as rounded medians; `round_to_cents` from `ledger_kit.utils.money`).
- [x] Verify: tests pass, `ruff check` clean.

---

## Task Z7 — `find_series` Phases 1 and 3, acceptance guard

**Covers**: REQ-ZS-08, REQ-ZS-09 (E3, E4, E6, E7, E7b), REQ-ZS-10, REQ-ZS-10b, REQ-ZS-11, §4.6

- [x] Write `tests/test_zs_find_series.py` (part 1):
  - **Tier 1 acceptance**: `test_zs_acceptance_e3_parallel_different_amounts_two_series`; `test_zs_acceptance_e4_parallel_same_amount_two_series` (trace per design §4.8: both series found by the `while` loop, no stride-2); `test_zs_acceptance_e6_two_supermarket_charges_no_series`; `test_zs_acceptance_e7_weekly_varying_amounts_no_series`; `test_zs_acceptance_e7b_weekly_shopping_no_series` — `find_series` on the `ledger_with_weekly_shopping` rows returns `[]`.
  - **Tier 1**: `test_stable_monthly_series_found`; `test_stable_weekly_needs_four`; `test_quarterly_pair_accepted_when_no_other_rows_in_span`; `test_yearly_pair_accepted_when_no_other_rows_in_span`.
  - **Tier 1 — span guard**: `test_quarterly_pair_rejected_when_other_rows_in_span`; `test_yearly_pair_rejected_when_other_rows_in_span`; `test_weekly_supermarket_key_makes_no_quarterly_series` — the E7b fixture plus a 27th row: still `[]`.
  - **Tier 2**: `test_find_series_empty_and_single_row`; `test_below_minimum_occurrences_no_series` (2 monthly, 3 weekly); `test_gap_tolerance_boundaries`; `test_duplicate_source_ref_does_not_crash`; `test_interleaved_series_not_merged`.
  - **Tier 3**: `test_find_series_row_order_invariant` — shuffled input gives identical series; `test_series_rows_are_subset_and_disjoint` — no row in two series; `test_series_rows_are_date_sorted`.
- [x] Implement `_other_rows_in_span`, `_accept`, `find_series` Phase 1 and Phase 3 (Phase 2 stubbed as "no change" until Z8).
- [x] Verify: tests pass, `ruff check` clean.

---

## Task Z8 — `find_series` Phase 2 (extend and merge)

**Covers**: REQ-ZS-09 (E1, E2), REQ-ZS-10c, REQ-ZS-14, §4.6, §4.8

- [x] Extend `tests/test_zs_find_series.py` (part 2):
  - **Tier 1 acceptance**: `test_zs_acceptance_e1_step_change_detected` — one series, six rows, `current_amount=15.99`, `price_steps == [(12.99, 15.99)]`; `test_zs_acceptance_e2_step_change_two_levels_merged` — one series, six rows, `price_steps == [(9.99, 12.99)]`; `test_downgrade_merged_with_downward_step`.
  - **Tier 1 — backward extension**: `test_early_step_first_charge` — 1 × 9.99 then 5 × 12.99 (step above 10%) → one series, one step; `test_early_step_second_charge` — 2 × 9.99 then 4 × 12.99.
  - **Tier 1**: `test_step_within_one_bucket_found` (12.99 × 3 then 13.79 × 3 is a single bucket).
  - **Tier 1 — guards**: `test_trial_charge_28_days_before_series_not_absorbed` — 0.49, then 14.99 × 3 starting 30 days later: the series has exactly the 3 rows of 14.99 and the 0.49 row stays outside; `test_stray_row_on_cadence_with_implausible_price_not_absorbed` (12.99 × 4 then 4.99 on the next date).
  - **Tier 2**: `test_extension_tolerance_boundaries`; `test_extension_picks_closest_candidate`; `test_phase2_terminates_on_many_rows` (200-row ledger finishes).
  - **Tier 3**: `test_step_at_every_position_found_once` — noise-free step 5–50% (whole percent, base whole euros 20–500) at k = 1..5 of 6 monthly charges → exactly one series with one step; `test_row_order_invariant_with_steps`.
- [x] Implement `_closest` and Phase 2a (forward and backward extension, re-segmenting the whole series) and 2b (merge consecutive non-overlapping series) in `find_series`; final sort of the result.
- [x] Verify: tests pass, `ruff check` clean.

---

## Task Z9 — Active series and service yearly cost

**Covers**: REQ-ZS-13a, REQ-ZS-13 (`yearly_cost`), design §3.1, §4.7

- [x] Write `tests/test_zs_active.py`:
  - **Tier 1**: `test_is_active_within_nominal_plus_tolerance`; `test_is_active_boundary_inclusive` — exactly `nominal + 3` days is active, one more is not; `test_service_yearly_cost_sums_active_series_only`.
  - **Tier 2**: `test_service_yearly_cost_no_series_is_zero`; `test_service_yearly_cost_max_date_none_is_zero`; `test_service_yearly_cost_two_aliased_keys_found_per_key` — rows of the two keys are never passed to one `find_series` call.
  - **Tier 3**: `test_is_active_monotone_in_max_date`.
- [x] Implement `is_active` and `service_yearly_cost`.
- [x] Verify: tests pass, `ruff check` clean.

---

## Task Z10 — Recurring-charge detector

**Covers**: REQ-ZS-12, REQ-ZS-13, REQ-ZS-45, REQ-ZS-47, REQ-ZS-48, Guiding principle 5, §5.1

- [x] Write `tests/test_zs_recurring_charge.py`:
  - **Tier 1**: `test_recurring_charge_fires_on_typical_input` — 1 alert, `detector == "zs.recurring_charge"`, `severity == "info"`, `source_refs` match the fixture rows in date order, all `data` keys of REQ-ZS-13 present; `test_recurring_charge_silent_on_clean_ledger`; `test_yearly_cost_is_current_amount_times_ppy`; `test_zs_acceptance_e1_yearly_cost_191_88`; `test_zs_acceptance_e3_two_alerts`; `test_zs_acceptance_e4_two_alerts`; `test_alias_resolves_counterparty_display_name`.
  - **Tier 1 — shopping**: `test_zs_acceptance_e7b_weekly_shopping_no_alerts_of_any_kind` (runs all five detectors through `run_all(namespace="zs")` once Z16 exists; here the recurring detector alone must return `[]`).
  - **Tier 2**: `test_empty_ledger_returns_empty_list`; `test_single_row_returns_list`; `test_none_aliases_does_not_raise`; `test_duplicate_source_ref_handled`; `test_two_monthly_charges_below_minimum`; `test_is_active_true_and_false` (dates relative to the ledger maximum); `test_amount_boundary_at_stable_ratio`; `test_source_refs_sorted_by_date_not_text` (`f.csv:9` before `f.csv:10`).
  - **Tier 3** (`max_examples=200`): `test_monthly_series_always_detected` (gap = 30 + jitter in [−3, 3], amounts within ±4%); `test_insufficient_occurrences_never_detected`; `test_row_order_invariant`; `test_yearly_cost_equals_current_price_times_12`; `test_source_refs_subset_of_input`; `test_detector_idempotent`.
- [x] Implement `detectors/recurring_charge.py` (`@register("zs.recurring_charge")`).
- [x] Verify: tests pass, `ruff check` clean.

---

## Task Z11 — Price-increase detector

**Covers**: REQ-ZS-14, REQ-ZS-15, REQ-ZS-16, REQ-ZS-48, REQ-ZS-10c, §5.2

- [x] Write `tests/test_zs_price_increase.py`:
  - **Tier 1**: `test_zs_acceptance_e1_price_increase_alert` — old 12.99, new 15.99, `extra_cost_per_year == "36.00"`, `yearly_cost == "191.88"`; `test_zs_acceptance_e2_price_increase_alert` (old 9.99, new 12.99); `test_downgrade_never_alerts`; `test_price_increase_silent_on_clean_ledger`; `test_step_between_5_and_10_pct_alerts` (12.99 → 13.79 × 3 each).
  - **Tier 1 — shopping**: `test_e7b_no_price_increase_alerts`.
  - **Tier 2**: `test_empty_ledger_returns_empty_list`; `test_single_row_returns_list`; `test_threshold_boundary_exactly_5pct_fires` and `test_just_below_5pct_does_not` (20.00 → 21.00 fires; 20.00 → 20.99 does not); `test_ratio_computed_from_rounded_medians`; `test_duplicate_source_ref_handled`; `test_two_steps_in_one_service_each_reported`.
  - **Tier 3** (`max_examples=200`): `test_price_step_above_5pct_always_fires` (±0.5% noise, step 7–45%, base 20–500, k = 1..5); `test_price_step_exactly_5pct_fires` (noise-free, k = 1..5); `test_price_step_below_5pct_never_fires` (±0.5% noise, base 100–500, step at most 3.9%, up or down); `test_stable_series_never_fires_price_increase`; `test_early_step_fires_exactly_once` (noise-free, 5–50%, k = 1..5); `test_source_refs_subset_of_input`.
- [x] Implement `detectors/price_increase.py` (`@register("zs.price_increase")`).
- [x] Verify: tests pass, `ruff check` clean.

---

## Task Z12 — Duplicate-subscription detector

**Covers**: REQ-ZS-17, REQ-ZS-18, REQ-ZS-19, REQ-ZS-20, §5.3

- [x] Write `tests/test_zs_duplicate_subscription.py`:
  - **Tier 1**: `test_zs_acceptance_e4_duplicate_alert_without_aliases` (one alert, `series_count == 2`); `test_zs_acceptance_e5_aliased_duplicate_alert` (`canonical_name == "STREAMING"`, regardless of amounts); `test_zs_acceptance_e3_no_duplicate_alert`; `test_duplicate_silent_on_clean_ledger`; `test_yearly_cost_is_sum_of_series_yearly_costs`.
  - **Tier 2**: `test_empty_ledger_returns_empty_list`; `test_single_row_returns_list`; `test_none_and_empty_aliases_do_not_raise`; `test_dormant_series_is_not_a_duplicate`; `test_same_key_amounts_exactly_10pct_apart_is_duplicate_and_beyond_is_not`; `test_three_series_two_qualifying_counts_only_qualifying`; `test_duplicate_source_ref_handled`.
  - **Tier 3** (`max_examples=200`): `test_source_refs_subset_of_input`; `test_row_order_invariant`; `test_idempotent`.
- [x] Implement `detectors/duplicate_subscription.py` (`@register("zs.duplicate_subscription")`).
- [x] Verify: tests pass, `ruff check` clean.

---

## Task Z13 — Free-trial-to-paid detector

**Covers**: REQ-ZS-21, REQ-ZS-22, REQ-ZS-23, §5.4

- [x] Write `tests/test_zs_free_trial_to_paid.py`:
  - **Tier 1**: `test_free_trial_fires_on_typical_input` (0.49 fourteen days before 14.99 × 3); `test_free_trial_silent_on_clean_ledger`; `test_trial_row_not_part_of_series`; `test_source_refs_include_trial_and_series_sorted_by_date_then_row` — trial `f.csv:10` before series rows `f.csv:9`-style refs are ordered by `(date, source_row)`, not as text.
  - **Tier 2**: `test_empty_ledger_returns_empty_list`; `test_single_row_returns_list`; `test_amount_boundaries_0_01_and_1_00_inclusive_1_01_excluded_0_00_absent`; `test_day_boundaries_1_and_35_inclusive_0_and_36_excluded`; `test_closest_trial_charge_chosen`; `test_trial_28_to_33_days_before_series_still_a_trial` (not absorbed into the series); `test_duplicate_source_ref_handled`.
  - **Tier 3** (`max_examples=200`): `test_source_refs_subset_of_input`; `test_row_order_invariant`; `test_never_fires_without_a_series`.
- [x] Implement `detectors/free_trial_to_paid.py` (`@register("zs.free_trial_to_paid")`).
- [x] Verify: tests pass, `ruff check` clean.

---

## Task Z14 — Charges-after-cancellation detector

**Covers**: REQ-ZS-24, REQ-ZS-25, REQ-ZS-26, §5.5

- [x] Write `tests/test_zs_charges_after_cancellation.py`:
  - **Tier 1**: `test_post_cancellation_alert_fires` (`severity == "critical"`, `total_charged_after` is the exact sum of the post rows); `test_silent_without_cancellation_dates` (`None` and `{}` → `[]`); `test_silent_on_clean_ledger`; `test_rows_outside_a_series_are_still_counted`.
  - **Tier 1 — canonical grouping**: `test_two_aliased_keys_give_one_alert` — `STREAMFLIX INTL` and `STREAMFLIXCOM` aliased to `streaming`, a cancellation date for `STREAMING`, post-cancellation rows under both keys → exactly one alert whose `source_refs` contain rows of both keys; `test_yearly_cost_sums_active_series_of_all_keys`; `test_yearly_cost_zero_when_no_active_series`.
  - **Tier 2**: `test_empty_ledger_returns_empty_list`; `test_single_row_returns_list`; `test_charge_on_cancellation_date_is_not_after` (strictly after); `test_unknown_service_in_cancellation_dates_ignored`; `test_date_map_keys_must_be_normalised_by_caller`; `test_duplicate_source_ref_handled`.
  - **Tier 3** (`max_examples=200`): `test_source_refs_subset_of_input`; `test_total_equals_sum_of_cited_rows`; `test_row_order_invariant`.
- [x] Implement `detectors/charges_after_cancellation.py` (`@register("zs.charges_after_cancellation")`) using `group_by_canonical` and `service_yearly_cost` (series found per key, rows aggregated per service).
- [x] Verify: tests pass, `ruff check` clean.

---

## Task Z15 — `compute_zombie_cost`

**Covers**: REQ-ZS-27, REQ-ZS-28, REQ-ZS-29, REQ-ZS-30, REQ-ZS-45, §6

- [x] Write `tests/test_zs_compute_zombie_cost.py`:
  - **Tier 1**: `test_cost_is_sum_of_rows_after_last_used` (fixture `ledger_with_zombie`: the last 2 charges); `test_source_refs_are_the_rows_after_last_used_sorted_by_date_row`; `test_yearly_cost_from_active_series`; `test_charge_on_last_used_date_excluded` (strictly after).
  - **Tier 1 — canonical grouping**: `test_two_aliased_keys_give_one_result`.
  - **Tier 2**: `test_empty_ledger_returns_zero_cost_entries` — a service in `last_used_dates` with no rows yields `cost_since_last_used == Decimal("0.00")`, `source_refs == []`, `yearly_cost == Decimal("0.00")` (REQ-ZS-30); `test_last_used_dates_none_returns_empty_list`; `test_last_used_after_all_charges_is_zero_cost_not_omitted`; `test_single_row_ledger`; `test_duplicate_source_ref_handled`; `test_no_system_clock_read` (monkeypatch `datetime`/`date.today` to raise).
  - **Tier 3** (`max_examples=200`): `test_cost_equals_sum_of_cited_row_amounts`; `test_source_refs_subset_of_input`; `test_row_order_invariant`.
- [x] Implement `ZombieCostResult` and `compute_zombie_cost` in `detectors/utils.py`.
- [x] Verify: tests pass, `ruff check` clean.

---

## Task Z16 — Registry integration

**Covers**: OD-ZS-01, OD-ZS-02, REQ-ZS-12, REQ-ZS-15, REQ-ZS-18, REQ-ZS-22, REQ-ZS-25

- [x] Write `tests/test_zs_registry.py` (use the ledger-core `_snapshot_registry` / `_restore_registry` fixtures; no `_clear_registry`):
  - `test_auto_discover_registers_five_zs_detectors` — names are exactly `zs.recurring_charge`, `zs.price_increase`, `zs.duplicate_subscription`, `zs.free_trial_to_paid`, `zs.charges_after_cancellation`.
  - `test_run_all_zs_namespace_on_empty_ledger_returns_empty_alerts`.
  - `test_run_all_passes_context_as_mapping_proxy_and_detectors_do_not_mutate_it`.
  - `test_e7b_run_all_produces_no_alerts_of_any_kind` — acceptance E7b through `run_all(ledger_with_weekly_shopping, namespace="zs", context={"aliases": None, "cancellation_dates": None})`.
  - `test_run_all_on_acceptance_fixtures_expected_detectors_fire`.
- [x] Implement `detectors/__init__.py` (`auto_discover("apps.zombie_subscriptions.detectors")` and the `run_zs_detectors` convenience wrapper).
- [x] Verify: tests pass, `ruff check` clean.

---

## Task Z17 — Settings and `config.toml`

**Covers**: REQ-ZS-07, REQ-ZS-40, REQ-ZS-42, REQ-ZS-43, REQ-ZS-44, §7, §10.1

- [x] Write `tests/test_zs_settings.py`:
  - **Tier 1**: `test_load_config_reads_aliases_and_demo`; `test_demo_dates_converted_with_fromisoformat` (strings become `datetime.date`; real TOML dates are accepted too); `test_parse_aliases_text_roundtrip`; `test_parse_dates_text_roundtrip`; `test_parse_dates_text_rejects_bad_date_with_clear_error` (the app shows a message, never crashes).
  - **Tier 2**: `test_parse_empty_text_returns_empty_dict`; `test_parse_ignores_blank_lines_and_whitespace`; `test_config_contains_no_threshold_constants` (REQ-ZS-42); `test_demo_section_has_at_least_3_last_used_and_1_cancellation`.
  - **Tier 3**: `test_format_then_parse_is_identity` for generated alias maps and date maps.
- [x] Create `apps/zombie_subscriptions/config.toml` (`[aliases]` with fictional services, `[demo]` as in design §10.1; no thresholds). Implement `settings.py` (`load_config`, `demo_inputs`, `to_date`, `parse_*_text`, `format_*_text`).
- [x] Verify: tests pass, `ruff check` clean.

---

## Task Z18 — Explanation support

**Covers**: REQ-ZS-31, REQ-ZS-32, REQ-ZS-33, REQ-ZS-34, REQ-ZS-37a, §9

- [x] Write `tests/test_zs_explain_support.py`:
  - **Tier 1**: `test_templates_cover_every_registered_zs_detector`; `test_every_template_fills_from_its_alert_data` — for one alert per detector (from the fixtures), `ledger_kit.explainer.explain_with_meta(..., client=None)` with no API key returns `source == "fallback"`, no unfilled `{placeholder}`, amounts in European format (`191,88 EUR`), and a cited `source_ref`.
  - **Tier 1**: `test_hallucinating_stub_is_rejected_by_number_guard` — `explain_with_meta(alert, rows, fallback_template=..., client=HallucinatingStubClient())` → `source == "fallback"` and `"99999.99"` in `rejected_numbers`; `test_stub_shape_matches_mock_client` (`chat` and `completions` are properties, `create` returns `choices[0].message.content`).
  - **Tier 2**: `test_stub_ignores_extra_kwargs`; `test_injected_number_not_in_any_fixture_alert`.
- [x] Implement `explain_support.py` (`TEMPLATES`, `HallucinatingStubClient`).
- [x] Verify: tests pass, `ruff check` clean.

---

## Task Z19 — Demo CSV generator and sample file

**Covers**: REQ-ZS-38, REQ-ZS-44, Finance Rules 5 and 6, §10

- [x] Write `tests/test_zs_demo_generator.py`:
  - `test_generator_is_deterministic` — two runs with `--seed 42` give identical bytes.
  - `test_demo_csv_parses_with_zero_quarantine` — `parse_csv` of the file: no quarantine, 300–400 rows, dates within 2026-05-01…2026-10-31, plain dialect.
  - `test_demo_counterparties_are_fictional` — no counterparty contains `SPOTIFY`, `ADOBE`, `DROPBOX`, `NETFLIX`, or other real-brand deny-list entries; person names appear only on salary/transfer rows.
  - `test_demo_contains_all_planted_patterns` — each key of design §10 exists with its pattern (E1–E5 shapes, free-trial pair 14 days apart, `GYMPLUS` rows after 2026-07-31, zombie candidates).
  - `test_demo_noise_merchants_follow_e7b_construction_and_produce_no_series`.
- [x] Implement the `zombie-demo` mode in `scripts/generate_samples.py` (replaces the stub entry in `MODE_HANDLERS`; `random.Random(42)` drives only the one-off shops) and add its provenance to `data/samples/README.md`.
- [x] Generate and commit `data/samples/zombie_demo_statement.csv`: `python scripts/generate_samples.py --mode zombie-demo --seed 42`.
- [x] Verify: tests pass, `ruff check` clean; `.gitignore` still allows `data/samples/`.

---

## Task Z20 — End-to-end demo test

**Covers**: REQ-ZS-38, REQ-ZS-44, REQ-ZS-52, REQ-ZS-49

- [x] Write `tests/test_zs_demo_e2e.py` (the test goes first and fails until the config and data line up):
  - `test_demo_config_keys_match_csv_normalised_keys` — every alias member and every key of `last_used_dates` and `cancellation_dates` in `[demo]` equals a normalised key in the demo CSV (`normalise_counterparty` of each `counterparty`); the alias name itself (`streaming`) is not required to be in the CSV. This catches `GYM PLUS` vs `GYMPLUS` and typos like `NETLIXINTL`.
  - `test_demo_dates_parse_with_fromisoformat`.
  - `test_demo_triggers_all_five_detectors` — ingest the CSV with `parse_csv` and `normalise`, filter to debit, `run_all(namespace="zs", context=<demo context, normalised>)`: at least one alert from each of the five detectors.
  - `test_demo_has_at_least_three_tombstones_with_nonzero_cost` — `compute_zombie_cost(...)` gives ≥ 3 entries with `cost_since_last_used > 0`.
  - `test_demo_noise_merchants_produce_no_alerts` — no alert cites a row of the grocery/noise merchants.
  - `test_demo_alert_source_refs_exist_in_csv`.
- [x] Fix `config.toml` / generator output until the test passes (names must match exactly).
- [x] Verify: tests pass, `ruff check` clean.

---

## Task Z21 — Streamlit app

**Covers**: REQ-ZS-01, REQ-ZS-02, REQ-ZS-03, REQ-ZS-04, REQ-ZS-35, REQ-ZS-36, REQ-ZS-37, REQ-ZS-37a, REQ-ZS-39, REQ-ZS-40, REQ-ZS-41, §7, §8

- [x] Write `tests/test_zs_app_logic.py` for everything that does not need a Streamlit runtime:
  - `test_app_py_first_lines_bootstrap_sys_path` — parse `app.py` source: the path bootstrap precedes the first `ledger_kit` import.
  - `test_app_uses_on_click_for_load_demo` — AST check: `st.button("Load demo data", ..., on_click=...)` is used and no `st.session_state[<widget key>] = ...` assignment appears under an `if st.button(...)` body.
  - `test_load_demo_callback_prefills_widget_keys` — call the callback logic from `settings` with a plain dict standing in for `session_state`: the keys `aliases_text`, `last_used_text`, `cancel_text`, `source`, `demo_loaded` are set.
  - `test_all_amounts_rendered_with_format_amount` — the view-model helper returns European-formatted strings (`"1.234,56 EUR"`).
  - `test_guard_badge_selection` — `source == "llm"` → 🤖 ✓; fallback without key → 📋; fallback with `rejected_numbers` → ⚠️ naming the number.
  - `test_alerts_grouped_critical_warning_info`.
- [x] Write `tests/test_zs_app.py` with `streamlit.testing.v1.AppTest` (`default_timeout=60`, detector registry snapshot/restore, `OPENAI_API_KEY` removed): the app starts without exception; after clicking **Load demo data** the 3 demo tombstones and the alerts of all five detectors render without exception; the hallucination toggle gives the fallback text with the ⚠️ badge naming `99999.99`; the zs detectors stay registered.
- [x] Implement `apps/zombie_subscriptions/app.py`: path bootstrap; `load_demo` callback defined before the widgets and attached with `st.button("Load demo data", on_click=load_demo)`; sidebar text areas keyed `aliases_text`, `last_used_text`, `cancel_text`; hallucination toggle; file uploader; ingestion cache by sha256; debit filter; `run_all`; `compute_zombie_cost`; explanation cache keyed `(alert.id, client_mode)`; Halloween graveyard CSS via `st.markdown(..., unsafe_allow_html=True)`; tombstone cards (name, "Died on", "Cost since then", "Yearly cost", collapsible `source_refs`); alert list by severity with guard badge and collapsible source rows; quarantine section. Put pure view-model code in `settings.py`/helpers so the tests above need no Streamlit.
- [x] Verify (manual smoke test, recorded in the PR): `streamlit run apps/zombie_subscriptions/app.py` starts; clicking **Load demo data** shows ≥ 3 tombstones and all five alert types without `StreamlitWidgetAlreadyInstantiatedError`; the hallucination toggle shows the ⚠️ badge with `99999.99`.
- [x] Verify: tests pass, `ruff check` clean.

---

## Task Z22 — Update `.kiro/steering/structure.md` (zombie section)

**Covers**: REQ-ZS-41, design §1; keeps the steering document consistent with the spec (requirements §13 supersedes the illustrative list)

- [x] Replace the `apps/zombie_subscriptions/` block of the layout tree in `.kiro/steering/structure.md` with the spec's file list:
  - `detectors/`: `__init__.py`, `utils.py`, `recurring_charge.py`, `price_increase.py`, `duplicate_subscription.py`, `free_trial_to_paid.py`, `charges_after_cancellation.py` (remove `last_use_gap.py` and `dormant_subscription.py`).
  - `tests/`: `conftest.py`, `test_zs_recurring_charge.py`, `test_zs_price_increase.py`, `test_zs_duplicate_subscription.py`, `test_zs_free_trial_to_paid.py`, `test_zs_charges_after_cancellation.py`, `test_zs_demo_e2e.py` plus the helper test modules (`test_zs_utils_normalise.py`, `test_zs_utils_helpers.py`, `test_zs_series_primitives.py`, `test_zs_segment_by_price.py`, `test_zs_find_series.py`, `test_zs_active.py`, `test_zs_compute_zombie_cost.py`, `test_zs_registry.py`, `test_zs_settings.py`, `test_zs_explain_support.py`, `test_zs_demo_generator.py`, `test_zs_app_logic.py`, `test_zs_scaffold.py`, `test_zs_fixtures.py`).
  - App root: `app.py`, `config.toml`, `settings.py`, `explain_support.py`; **remove `requirements.txt`** from the zombie block (the root `requirements.txt` is the only one; an app-level file would hide it on Streamlit Community Cloud).
  - Add `scripts/generate_samples.py` and `data/samples/zombie_demo_statement.csv` to the tree if absent; add `requirements.txt` at the repository root.
  - Leave the `phantom_invoices/` block untouched.
- [x] Add a one-line note under "Package boundaries": the zombie app may import `ledger_kit` and its own `detectors/`, `settings.py`, `explain_support.py`.
- [x] Verify: the tree in `structure.md` matches `requirements.md` §13 for the zombie app; no other section of the file changed.

---

## Task Z23 — Final integration check

**Covers**: REQ-ZS-45, REQ-ZS-47, REQ-ZS-48, REQ-ZS-49, REQ-ZS-50, REQ-ZS-51

- [x] Run `pytest apps/zombie_subscriptions/ --cov=apps/zombie_subscriptions --cov-fail-under=80`, then the full `pytest` to confirm ledger-core is unaffected.
- [x] Confirm every acceptance example has a named test: E1, E2, E3, E4, E5, E6, E7, E7b (`test_zs_acceptance_e*`), plus the downgrade test.
- [x] Confirm all three tiers exist for each of the five detectors and for `compute_zombie_cost`, and that all mandatory properties of REQ-ZS-48 are present with `@settings(max_examples=200)`.
- [x] Confirm no test or module reads the clock (`date.today()`, `datetime.now()`), no fixture or sample contains a real brand or person name outside Finance Rule 5 placeholders, and `apps/zombie_subscriptions/requirements.txt` does not exist.
- [x] Confirm `ruff check .` and `ruff format --check .` pass with zero warnings.
- [x] Fix any coverage gaps or lint issues found.

---

## Task ZSA1 — Amendment A-ZS-01: one public `run_pipeline` (session 10b, benchmark D-BM-10)

**Covers**: A-ZS-01, design §7 amendment. Refactor only: no behaviour change, no detector change.

- [x] Tests first in `apps/zombie_subscriptions/tests/test_zs_pipeline.py`: the demo statement gives
  19 alerts and the same 3 zombies as before; CSV and Norma 43 demos give equal alert counts;
  credits are not in `debit_ledger`; quarantine is returned; the optional `cache` avoids a second
  read; `_ingest` of `app.py` still returns what it returned.
- [x] Add `Pipeline`, `ingest_statement` and `run_pipeline` to `settings.py`; make `app.py` call
  `run_pipeline` (`_ingest` stays as a wrapper). All existing tests stay green.
