## Correction
All synthetic prices and promotions have been removed. No verified feed is connected. Price cards, comparison dialogs and basket totals now report unavailable data. Product catalog and local shopping list remain available.

# סל־סל · Compare Prices

Public site: https://danielbarguy.github.io/compare-prices/

Every push to `main` publishes the contents of `dist/` to GitHub Pages.

Local Hebrew RTL supermarket comparison prototype. Run `npm run dev` or `node server.mjs`, then open http://localhost:3000. No packages required; Node 18+.

Implemented: product search, category and promotion filters, price sorting, five-chain comparison dialogs, quantity-aware whole-basket comparison, local basket persistence, responsive layout, keyboard search and dialogs.

**All displayed prices and promotions are synthetic demo fixtures. No live price feed or automatic refresh is connected yet.** This is explicitly disclosed in the interface. Only the milk barcode is verified; other IDs are demo identifiers. Retailer-level values do not claim a specific branch. Product images are remotely hosted reference assets; review licensing and cache permitted assets before public release.

Claude Code is researching official sources in DATA-SOURCES.md. Production ingestion must key prices by chain/store/barcode, preserve source timestamps, fetch incremental prices and promotions, check files every 15 minutes, avoid overlapping fetches, handle rate limits with backoff, expire promotions, and distinguish club/quantity eligibility. A polling schedule cannot make source publications more frequent.

Validation: `npm run check`; comparison uses integer cents for basket arithmetic. Server binds to loopback only.

Image reference pages:
- https://www.ayaakov.co.il/products/item/41
- https://peppersmarket.shopo.co.il/?catalogProduct=12053
- https://shoppy.co.il/products/barilla-pasta-spaghetti-no-5
- https://www.ebay.com/itm/365347524484
- https://www.ewines.co.il/products/קוקה-קולה-1-5-ליטר
- https://shoppy.co.il/products/osem-petit-beurre-tea-biscuits
