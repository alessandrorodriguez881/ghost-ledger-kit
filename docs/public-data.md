# Public data

Back to the [README](../README.md).

## Public context: the INE consumer price index

A price increase says little on its own: 18 % is more or less depending on what prices did in the same months. When `zs.price_increase` has already raised an alert, it can add one neutral sentence of official context: how the Spanish consumer price index (IPC, INE series IPC290751, base 2025) changed between the same two months. It is context, not a verdict: it never decides whether an alert fires, changes a severity or a `source_refs` list, and gives no advice.

- **A committed file, never the network.** The index is a snapshot in `data/public/ine_cpi_ipc290751.json`, read by `ledger_kit/public_data/`. The apps, the tests and the explanation layer never call the network. Only the developer runs `python scripts/fetch_ine_cpi.py`, which makes one request, checks the result and replaces the file only if every check passes.
- **Same promise as every other figure.** The index values and the percentage are named fields of `Alert.data`, so the number guard admits them and rejects any other number. When a month is not covered by the snapshot the alert carries no CPI field at all.
- **Attribution.** The INE data keeps its own licence (CC BY 4.0) and is not covered by the MIT licence of this repository. The Zombie Subscriptions page shows this notice once, below its alerts:

> Elaboración propia con datos extraídos del sitio web del INE: www.ine.es
>
> Licence: CC BY 4.0
>
> The INE does not take part in, sponsor or support this reuse.

Source, series, licence and refresh steps are in `data/public/README.md`.
