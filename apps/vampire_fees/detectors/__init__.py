"""Vampire-fees detectors: importing this package registers the four vf.* detectors."""

from ledger_kit.detectors import auto_discover

auto_discover("apps.vampire_fees.detectors")
