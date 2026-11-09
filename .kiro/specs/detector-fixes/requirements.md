# detector-fixes — Requirements

Spec created in session 10d from the first full benchmark run (`docs/benchmark.md`, seed 2026,
200 scenarios per app) and the findings F2 and F3 of `.kiro/specs/benchmark/design.md` §8.
Finding F1 of that list was a generator error and is already handled there (D-BM-20); it is not
part of this spec.

Ids are `REQ-DF-nn`. EARS keywords: *shall*, *when*, *while*, *where*, *if ... then*. Every
requirement has at least one acceptance example that becomes a test. Facts below were read from
the code, the specs and four exported benchmark scenarios; nothing was run (see §5 of
`design.md`).

## 0 — Scope and principles

Two real weaknesses are fixed, each on a principle that does not depend on the benchmark seed:

1. **A supplier may have several accounts** (`pi.iban_change`). The supplier master may list
   several valid IBANs for one tax id. An invoice or payment on any of them is not a poltergeist
   IBAN. Today REQ-PI-09 keeps the first row and ignores the others, so the second legitimate
   account raises a critical alert. (Finding F3.)
2. **A recurring charge needs stable amounts as well as regular dates** (`zs.recurring_charge` and
   the series finder every zombie detector uses). The looser the amount rule, the more evidence
   of a cadence the finder must ask for. Today a "variable bill" (amounts only within 10 % of
   their median) is accepted from any three monthly or four weekly charges picked out of a
   stream of other charges of the same shop, so weekly groceries and fuel stops look like
   subscriptions. (Finding F2.)

Not in this spec: changes to any threshold constant, label, hard negative, seed or scenario
count (REQ-DF-18); the wording fix of FU-P3; the README and Home page sentences.

Terms: *accepted account* = the `iban_key` of a master IBAN that is present and valid (REQ-PI-23).
*Variable bill* = a cadence run accepted by branch 3 of REQ-ZS-10a (no step, every amount within
`AMOUNT_MATCH_RATIO` of the median, but not one price level). *Foreign row* = a debit row of the
same normalised key, dated from the first to the last charge of a run (inclusive), that is not
part of the run.

---

## 1 — Phantom invoices: several accounts per supplier (`pi.iban_change`)

- **REQ-DF-01** *(all master rows are kept; amends REQ-PI-09)* The supplier master lookup shall
  keep every master row of a `tax_key`, in `source_ref` order. The first row names the supplier
  (name and identity for the alert); every row of the tax id contributes its IBAN to the
  supplier's accepted accounts. Rows with an empty `tax_key` are still not suppliers (DN-12).

  *Acceptance.* Master rows `sup.csv:0` (account A, valid) and `sup.csv:1` (account B, valid)
  with the same tax id: the supplier has accepted accounts `{A, B}` and is named by row 0.
  Shuffling the frame does not change the result (order by `source_ref`).

- **REQ-DF-02** *(an invoice on any accepted account is silent)* When an invoice has a valid IBAN
  and its supplier has at least one accepted account, if the invoice IBAN's `iban_key` equals any
  accepted account, then `pi.iban_change` shall raise no alert for that invoice.

  *Acceptance.* Accepted accounts `{A, B}`: an invoice on A → no alert; an invoice on B → no
  alert; an invoice on `a` written in lower case with spaces (REQ-PI-08 `iban_key`) → no alert.

- **REQ-DF-03** *(an invoice on another account still alerts, and cites every master row)* When
  an invoice has a valid IBAN that equals none of the supplier's accepted accounts, then the
  detector shall raise the critical `invoice_iban_differs_from_master` alert of REQ-PI-24 with
  these properties: `source_refs` are the invoice, the **first master row of the tax id** (it names
  the supplier) and **every master row of the supplier that has an accepted account**, in
  natural order without repeats (Finance Rule 2); the keys of `Alert.data` are
  unchanged; `master_iban_masked` is the masked form of the first accepted account in
  `source_ref` order; `last4_identical` is true when the masked invoice IBAN equals the masked
  form of any accepted account.

  *Acceptance.* Accepted accounts `{A, B}` (rows 0 and 1), invoice on C (valid, not in the
  master): one critical alert, `source_refs == ["inv.csv:0", "sup.csv:0", "sup.csv:1"]`,
  `master_iban_masked == mask_iban(A)`, `data` keys equal to today's key set. A third account is
  still a poltergeist. With one master row the alert is identical to today's (REQ-DF-09).

- **REQ-DF-04** *(payments follow the same rule)* When a debit payment is attributed to a master
  supplier (REQ-PI-25), its IBAN is valid and the supplier has at least one accepted account, if
  the payment IBAN equals any accepted account then no alert is raised; otherwise the critical
  `payment_to_non_master_iban` alert is raised with the same `source_refs` (the payment, the
  naming row and every row with an accepted account) and `master_iban_masked` rules as
  REQ-DF-03.

  *Acceptance.* Accepted accounts `{A, B}`: a debit to B, name written as the supplier → no
  alert; a debit to C → one critical alert citing the payment and both master rows.

- **REQ-DF-05** *(no usable account, no comparison)* If a supplier has no accepted account (every
  master IBAN of the tax id is missing or invalid), then the detector shall not raise a
  `…differs…` alert for its invoices or payments, as today (REQ-PI-24).

  *Acceptance.* Row 0 has an invalid IBAN, row 1 has an empty IBAN; an invoice on a valid IBAN →
  no differs alert. If row 1 holds a valid IBAN B, the invoice on B → no alert and an invoice on
  C → critical alert (row 0 does not count as an account).

- **REQ-DF-06** *(every master row is checked for its own IBAN; amends REQ-PI-24)* When a master
  row, whether it is the first of its tax id or a later one, has an IBAN that is present and
  invalid, then the detector shall raise one `iban_invalid` warning for that row, citing that
  row only.

  *Acceptance.* Rows 0 (valid) and 1 (same tax id, checksum broken): one warning citing
  `sup.csv:1`. Today the second row is ignored and raises nothing.

- **REQ-DF-07** *(rows of one tax id are one supplier for attribution; amends REQ-PI-25)* The
  attribution of a payment (name first, then IBAN) shall count a supplier once, however many
  master rows share its tax id, and shall attribute a payment sent to **any** accepted account of
  a supplier to that supplier when the name does not decide. A name or an account shared by two
  different tax ids still falls through, as today.

  *Acceptance.* Two rows of one tax id carry the supplier name N: a payment to N is attributed
  (one supplier, not two hits). A payment whose counterparty name matches nobody but whose IBAN
  is B (second account) is attributed to that supplier. Two suppliers with different tax ids and
  the same name: not attributed by name.

- **REQ-DF-08** *(the master alone decides)* The accepted accounts shall come from the supplier
  master only. An IBAN seen on an invoice or on a payment shall never join them, whatever the
  number of times it appears.

  *Acceptance.* Accepted accounts `{A}`; five invoices on C: five critical alerts.

- **REQ-DF-09** *(one row per tax id behaves as before)* Where every `tax_key` of the master has
  exactly one row, the output of `pi.iban_change`, `pi.reconciliation` and the attribution shall
  be identical to the output before this spec. The demo master has 25 rows with 25 different tax
  ids; the demo still gives 9 phantom alerts (3 critical, 6 warning).

  *Acceptance.* `tests/test_showcase_app.py` (`PI_DEMO_ALERTS = 9`) and
  `apps/phantom_invoices/tests/test_pi_demo_e2e.py` pass unchanged.

---

## 2 — Zombie subscriptions: stable amounts as well as regular dates (series finder)

- **REQ-DF-10** *(a weekly run cannot be a variable bill; amends REQ-ZS-10a(3))* The series
  finder shall accept a cadence run as a variable bill only when its interval type is monthly,
  quarterly or yearly. A weekly run shall be accepted only as a stable series (one price level)
  or as a step-change series (REQ-ZS-10a (1) and (2)). The set of intervals that may be variable
  bills is the named constant `VARIABLE_BILL_INTERVALS` (Finance Rule 7).

  Reason: variable weekly spending (groceries, fuel, transport) is the usual pattern of
  everyday shopping, while a bill that varies by a few percent every week is not a pattern the
  detector is meant to name; REQ-ZS-09 E7 already says it gives no alert.

  *Acceptance (E7c).* Four weekly charges at one shop of 100.00, 104.50, 109.00 and 113.50 (each
  step 4.5 %; all within 10 % of the median 106.75; no two of them within 2 % of a common
  median) give **no series** and no `zs.recurring_charge` alert. Today they give one weekly
  series with `current_amount` 106.75. Four weekly charges of 100.00 still give one stable
  series (E-stable), and 100.00, 100.00, 108.00, 108.00 weekly still give one step-change
  series.

- **REQ-DF-11** *(a variable bill needs an exclusive span; generalises REQ-ZS-10b)* If a cadence
  run is accepted only as a variable bill, then the series finder shall reject it when the key
  has at least one foreign row. REQ-ZS-10b (quarterly and yearly series) is unchanged.

  Reason: a utility bill that varies by a few percent is recognised by being the only thing the
  merchant charges in that period. Three similar amounts picked out of a stream of other charges
  of the same shop are a coincidence of the stream, not a bill.

  *Acceptance (E7d).* Three monthly charges of 90.00, 95.00 and 100.00, 30 days apart, nothing
  else under the key: one monthly series with `current_amount` 95.00 (unchanged). The same three
  charges plus one purchase of 20.00 under the same key 10 days after the first: **no series**.
  Benchmark case `zs-0000`: NIMBUSBOX groceries of 115.63 (2025-06-04), 119.51 (2025-07-02) and
  114.75 (2025-07-30) with six other charges of the shop between them: no series.

- **REQ-DF-12** *(stable and step-change series are not touched)* The series finder shall keep
  accepting a run that is one price level (within `STABLE_AMOUNT_RATIO` of the median) or a
  step-change series exactly as before, whatever other rows the key holds. Parallel series of one
  key (E3, E4, benchmark Z11 to Z13) and a subscription at a shop that also sells other things
  are therefore still found.

  *Acceptance.* Three monthly charges of 20.00 and one purchase of 12.50 at the same key between
  the first and second charge: one monthly series of three charges (unchanged). E3, E4 and E5 of
  REQ-ZS-09 pass unchanged.

- **REQ-DF-13** *(extension and merge obey the same rules)* When the finder extends a series by
  one row or merges two series (design phase 2), the resulting run shall be judged by the same
  segmentation and acceptance rules as REQ-DF-10 and REQ-DF-11. A run that was stable or
  step-change and becomes a weekly variable bill, or a variable bill with a foreign row in its
  span, after an extension or merge shall not be accepted in that form.

  *Acceptance.* Four equal weekly charges of 50.00 and a fifth of 52.50 the following week (5 %
  step on a single-row edge, REQ-ZS-10a) are still one weekly step-change series. Four weekly
  charges of 100.00, 104.50, 109.00, 113.50 plus a fifth of 118.00 give no series.

- **REQ-DF-14** *(the flag is part of the series)* `Series` shall carry whether it was accepted as
  a variable bill, so that the acceptance guard (REQ-DF-11) does not have to recompute the
  segmentation. The new field has a default (`False`) so that existing constructions of `Series`
  stay valid.

  *Acceptance.* `_segment_by_price` returns `variable=True` for the variable-bill branch only;
  stable, step-change and ambiguous-split series have `variable=False`.

- **REQ-DF-15** *(demo and acceptance examples unchanged)* The zombie demo statement shall still
  give 3 tombstones and 19 alerts. REQ-ZS-09 E1 to E7b pass unchanged. The demo's recurring
  charges are all stable or step-change (one price level, or one step such as 12.99 to 15.99), so
  the two rules above remove nothing from it.

  *Acceptance.* `tests/test_showcase_app.py` (`ZS_DEMO_ALERTS = 19`, `ZS_DEMO_TOMBSTONES = 3`),
  `test_zs_demo_e2e.py`, `test_zs_find_series.py`, `test_zs_series_primitives.py` pass unchanged,
  except a test that encodes a weekly variable bill, which is amended in its own task and named
  in the task list.

---

## 3 — Proof

- **REQ-DF-16** *(proved by unit tests and by a re-run at the same seed)* Each fix shall be
  proved by (a) unit tests written before the code, including a Hypothesis property per fix,
  and (b) a re-run of `python scripts/benchmark.py` at the committed seed and scenario count
  (2026, 200), with the figures recorded in the table of `.kiro/specs/benchmark/design.md` §8.
  No number is written before it is measured.

  *Acceptance (expectations, not pass marks; D-BM-13 forbids a score gate).*
  - After the phantom fix: `pi.iban_change` has **0** false alarms on `two_legit_ibans` (the
    cause is removed for every instance, not a share of them), precision of `pi.iban_change`
    `1.0000`, recall unchanged `1.0000`, phantom precision `1.0000`.
  - After the zombie fix: the false alarms of `zs.recurring_charge` on `fuel_irregular` and
    `weekly_groceries_irregular` fall sharply from 29 (the first measurement) and the recall of
    every zombie detector stays at its post-D-BM-20 value. Any remaining false alarm is listed
    with its scenario id and its rows, its cause is read, and it is either a further finding of
    this spec or an accepted limit of REQ-DF-20. It is not removed by tuning.

- **REQ-DF-17** *(spec text is amended)* The text of REQ-PI-09, REQ-PI-24 (master row bullet),
  REQ-PI-25, REQ-ZS-10a(3) and REQ-ZS-10b shall be amended in their own specs, each with a
  one-line note naming REQ-DF and the date, so that no requirement still says the opposite of
  the code.

  *Acceptance.* A grep of `.kiro/specs/phantom-invoices/requirements.md` for "the others are
  ignored" finds nothing; `.kiro/specs/zombie-subscriptions/requirements.md` states that a
  variable bill is monthly, quarterly or yearly and needs an exclusive span.

---

## 4 — Hygiene and limits

- **REQ-DF-18** *(no tuning)* This spec shall not change any numeric threshold constant of a
  detector (`STABLE_AMOUNT_RATIO`, `AMOUNT_MATCH_RATIO`, `INTERVAL_TOLERANCE_DAYS`,
  `MIN_OCCURRENCES_*`, `PRICE_INCREASE_MIN_RATIO`, and the phantom tolerances), nor the seed,
  the scenario count, a label or a hard negative of the benchmark.

  *Acceptance.* `test_zs_utils_normalise.py` and the phantom constant tests pass unchanged; the
  diff of `scripts/generate_benchmark.py` is empty for these tasks.

- **REQ-DF-19** *(property tests, deterministic)* Every property test of this spec uses
  `settings(max_examples=200)`, builds its dates explicitly (no clock) and uses only synthetic
  names, IBANs and tax ids that follow Finance Rule 5.

  *Acceptance.* The new tests contain no call to the clock and no real identifier.

- **REQ-DF-20** *(honest limits)* The fixes leave two known limits, which the benchmark page
  and `docs/benchmark.md` shall keep reporting through the results, not through prose:
  1. A genuine variable bill that has another charge of the same merchant inside its span (for
     example a utility bill and a one-off fee) is no longer reported as a series (REQ-DF-11).
  2. Charges of one shop that happen to lie on one price level (within 2 % of the median) at a
     regular cadence are still a series. Such a coincidence is rare for random amounts but not
     impossible, and the detector cannot tell it from a real subscription.

  *Acceptance.* Both limits are tested as documented behaviour (a test per limit) so that a later
  change cannot widen or remove them silently.

---

## 5 — Open decisions for the owner

- **OD-DF-01** Should a variable bill with a foreign row in its span be rejected (REQ-DF-11) or
  only downgraded? The spec rejects it because a downgraded alert would still list the charge as
  a recurring series. Reversible by removing the guard for `variable` series.
- **OD-DF-02** With several accepted accounts, the alert text names the first one
  (`master_iban_masked`). Adding `master_iban_count` to `Alert.data` is more honest but changes
  the key set that `test_pi_iban_change.py` pins. Default here: keep the key set; the UI still
  lists every master row through `source_refs` (Finance Rule 2).
- **OD-DF-03** A second master row with the same tax id but a different **name** is treated as
  the same supplier (the tax id identifies the legal entity). If the owner prefers to treat a
  differing name as a data error, REQ-DF-01 needs an extra quarantine rule.
- **OD-DF-04** REQ-DF-10 excludes weekly runs from the variable-bill branch as a class. The
  alternative (a longer minimum number of charges for weekly variable runs) is a threshold and
  would need the owner's decision and a REQ-DF-18 exception. Default here: exclude the class.
