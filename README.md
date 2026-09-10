# סל־סל · Compare Prices

Hebrew local supermarket comparison using official price-transparency XML files. No synthetic price fixtures are served.

## Run

Node 18+ and Python 3.9+ (standard library only):

```
node server.mjs
```

Open http://localhost:3000. The server binds to loopback. It checks official sources every 15 minutes while the process is running and the machine is awake and online. `python3 -B scripts/sync.py` runs a manual sync. Public portal login sessions are kept only in memory; no personal credentials are used.

On the first run, the app downloads the public locality and branch directories. Select one to 24 branches in the interface to import their current official price files. Generated source files and branch snapshots stay in the local `data/` directory and are intentionally excluded from Git.

## Data

- Raw downloaded official files: `data/raw/`.
- Durable per-branch snapshots: `data/stores/`, written atomically.
- Source filename, publication time, import time, SHA-256 and price-change time are retained.
- PriceFull establishes a branch baseline; available subsequent Price files update it. PromoFull and Promo are processed separately. The collector skips previously imported filenames and retains last successful data on failure. First sync cannot reconstruct incremental files no longer exposed by the publisher; source timestamps are shown instead of claiming real-time till prices.
- Cross-chain matches use identical published item codes for non-weighted ItemType=1 products. Internal/weighted codes are namespaced by chain.
- Prices are integer agorot. Missing products make a basket incomplete and prevent a cheapest-full-basket claim.
- Promotions are shown with validity windows, public club/coupon fields and source descriptions. They are NOT automatically applied to price comparisons or baskets. Promotion eligibility, combinations, quantity deals and club mappings need further work.
- The directory includes all 1,272 named localities in the government dataset (the code-zero non-locality row is excluded), and 878 branch records from 7 chains. A locality in the search does not imply retail coverage. Published branch lists may contain historical entries or missing city/address fields. Unknown cities stay unknown.
- Choose up to 24 branches through the city / chain / address search. A selection imports real prices on demand, saves `data/selection.json` and is checked every 15 minutes. Only the current selection is loaded into server memory; raw files and previous branch snapshots remain on disk. This is a local, single-user comparison, not a multi-user service.
- Directory metadata refreshes daily during a price sync; locality source is the government dataset archived in `data/localities-source.json`. Published prices do not establish stock availability.
- The shopping list is stored locally in this browser. Legacy demo baskets are not reused.

## Sources

- https://prices.shufersal.co.il/
- https://prices.carrefour.co.il/
- https://www.rami-levy.co.il/he/price-transparency
- https://url.publishedprices.co.il/ (public RamiLevi and Yohananof accounts; empty passwords)
- https://laibcatalog.co.il/ (linked by https://victory.co.il/parallel/)

Directory adapters: Shufersal, Carrefour, Rami Levi, Yohananof, Victory, Osher Ad, Mahsanei Hashuk. Initial prices loaded for 14 branches. Osher Ad public read-only access was verified in the Israeli Consumer Council public transparency guide: https://www.consumers.org.il/item/transparency_price . Dabah connection is pending explicit approval following an automatic review block; it is not represented as connected.

Government localities source: https://data.gov.il/api/3/action/datastore_search?resource_id=5f75cd96-d670-43b0-bf6d-583436c5d054&limit=5000

Victory and Mahsanei Hashuk use the public laibcatalog webapi: `/webapi/api/getfiles?edi={chainId}` and `/webapi/{chainId}/{filename}`. Adapter details were located using the source of il-supermarket-scraper 1.0.12 (MIT), then independently verified against downloaded XML; the package is not installed or executed.
- See `DATA-SOURCES.md` for the source research notes created during the Claude Code collaboration.

## Validation

```
node --test tests/catalog.test.mjs
python3 -B tests/test_ingest.py
python3 -B tests/test_directory.py
node --check dist/app.js
```

Tests check provenance against original files, branch identity, quantities, incomplete baskets, selection isolation and promotion expiry. Browser UI testing has not been requested or performed. Optional WebMCP registration is feature-detected; native browser WebMCP verification is unavailable.

Product pictures are external reference images matched by barcode. Source pages: https://www.ayaakov.co.il/products/item/41 ; https://peppersmarket.shopo.co.il/?catalogProduct=12053 ; https://shoppy.co.il/products/barilla-pasta-spaghetti-no-5 . Confirm image reuse rights before publishing.

## GitHub Pages

The application now requires its local Node/Python service for official source ingestion and comparison APIs. GitHub Pages can only host static files, so it is not a working deployment target for this version. Run it locally until a server-backed deployment is configured.
