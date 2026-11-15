# Tasks: haunted-design

Test first: each task writes the failing test, then the code. Nothing can be run in this session;
the user runs `ruff` and `pytest` afterwards.

- [x] HD1 Spec: requirements, design, tasks (this folder).
- [x] HD2 Icons. Test `tests/test_ui_icons.py` (REQ-HD-05), then `ledger_kit/ui/icons.py`.
- [x] HD3 Theme. Test `tests/test_ui_theme.py` (REQ-HD-01 to 04, 07, 08, 12, 13), then
  `ledger_kit/ui/theme.py`.
- [x] HD4 Landing. Test `tests/test_ui_landing.py` (REQ-HD-09 to 11), then
  `ledger_kit/ui/landing.py`.
- [x] HD5 Showcase entry. Update `streamlit_app.py`: icon names in `PAGES`, plain titles, new Home,
  Benchmark masthead; update the pinned titles in `test_showcase_app.py` and
  `test_benchmark_page.py`.
- [x] HD6 Zombie Subscriptions: theme, tombstone icon, section headings, severity badge, critical
  container key; update `test_zs_app.py` (title, palette).
- [x] HD7 Phantom Invoices: same; update `test_pi_app_logic.py` (title).
- [x] HD8 Vampire Fees: same; update `test_vf_app_logic.py` (title, coffin card text).
- [x] HD9 Every page renders, each app uses its accent, proof strip equals the committed files,
  demo numbers equal the apps: `tests/test_ui_pages.py` (REQ-HD-02, 10, 14, 15).
- [x] HD10 Final read-through against the requirements; list of changed files.

## Session 26: Home with one clear moment (chosen by the owner on 15 Nov)

Chosen by the owner on 15 Nov from the three improvements of the fresh jury of 14 Nov. Test first;
nothing can be run in this session, the hooks lint each file and run the tests when it stops.

- [x] HD11 Spec: requirements REQ-HD-16 to REQ-HD-23, design note DN-HD-11 to DN-HD-17, these
  tasks.
- [x] HD12 Tests of the moment and the layout: `tests/test_home_moment.py` (REQ-HD-16 to 23).
- [x] HD13 Update the tests that pin the Home layout: `test_judge_path_pages`,
  `test_ui_theme`, `test_showcase_requirements`, `test_home_example` (README step 1),
  `test_showcase_app` (Home renders within the timeout).
- [x] HD14 `ledger_kit/ui/theme.py`: `MOMENT_CSS`, tile rules.
- [x] HD15 `ledger_kit/ui/landing.py`: `Moment`, `moment_html`, tiles with a drawing.
- [x] HD16 `apps/home_tiles.py`: `pick_alert`, `tile_signatures`, `home_moment`.
- [x] HD17 `streamlit_app.py`: `home()` in the new order, the expander `How it works`.
- [x] HD18 `README.md`: For judges step 1, one Decisions row; list of changed files.

## Session 26b: fixes after the owner's review of session 26

- [x] HD19 Owner's run after session 26: ruff clean, 4,025 passed, 1 skipped, 2 failed.
- [x] HD20 `test_home_moment.py`: the timing rule is compared in whole milliseconds (1.3 + 0.4 was 1.7000000000000002); the rule itself is unchanged.
- [x] HD21 `test_benchmark_page.py`: the entry test allows only `apps.home_tiles`; REQ-SC-03 amended (showcase spec), `structure.md` lists `apps/home_tiles.py`.
