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
