# Kadai demo video

An automated, narrated-by-captions walkthrough of the Kadai order-to-audit app,
recorded with Playwright against the deployed demo instance.

- **Video:** `kadai-demo.mp4` — H.264, 1280×720, **7:57**, no audio
- **Script:** `record.mjs` — one browser context, one continuous recording
- **Scene stills:** `screens/` (one or more per scene)
- **Evidence:** `assets/` — the invoice PDF, its rendered page, the CSV/Excel
  exports downloaded during the run

## Re-run it

```bash
cd demo
npm install                 # playwright is the only dependency
npx playwright install chromium
node record.mjs             # records, writes kadai-demo.webm, encodes kadai-demo.mp4
```

Against a local stack instead:

```bash
BASE_URL=http://localhost:3000 node record.mjs
```

| Variable | Default | What it does |
| --- | --- | --- |
| `BASE_URL` | `https://13-207-33-205.sslip.io` | App origin to record |
| `SPEED` | `1` | Divides every caption pause: `1.1` faster, `0.9` slower |
| `SLOWMO` | `250` | Playwright `slowMo` in ms |
| `DRY` | off | Runs every scene but stops before each write (order, approval, invoice, dispatch, payment, credit note, issue, complete, overhead). Use it to validate selectors without touching data |
| `SKIP_ENCODE` | off | Keep only the `.webm` |

The runner catches each scene, screenshots a failure as `screens/fail-<id>.png`
and carries on, then prints a per-scene summary and the video length. Write
steps are verified against the API response (a swallowed click is retried once,
a 4xx is surfaced with the server's message).

## What it shows

| Scene | What happens |
| --- | --- |
| 1 | Title card, the problem, login screen |
| 2–3 | Salesman A signs in; dashboard scoped to her own book |
| 4–5 | Creates a 40-packet order for Retailer A; state timeline |
| 6 | Goes offline, queues a 120-packet order, shows `Pending (1)`, reconnects, syncs with no duplicate |
| 7 | Switches the whole UI to Tamil and back |
| 8 | Admin inbox: stock cover, GST preview, approve (audit row in the same transaction) |
| 9 | GST invoice, WeasyPrint PDF (shown as a rendered page), dispatch posting the FG issue |
| 10 | Records a ₹1,000 payment with allocation, outstanding and ageing |
| 11 | Credit note with restock; the posted invoice is never edited |
| 12 | The shortage on the second order and the Loop Closer batch plan |
| 13–14 | Production plans a draft run from the BOM, issues 10.5 L oil (live +5% chip) |
| 15 | Completes 188 good / 6 damaged / 9 cartons; stored variance snapshot |
| 16 | Cost sheet (materials 4,120.23 + overheads 1,800 → 31.49 per packet) and the Leakage Radar report card and bridge |
| 17 | Accountant: sales register, CSV/Excel exports, reconciliation ticks |
| 18 | Owner: leakage tile, variance alerts, reorder lines, the trigger-enforced audit rules |
| 19 | Closing card (stack and roles) |

The cost and leakage captions are read from the API at record time, so a
restock that changes the weighted-average flour rate cannot make the narration
disagree with the screen.

## Notes and limits

- Playwright records no audio; every explanation is a caption banner injected
  into the page. A red dot follows the pointer so clicks are visible.
- Captions are DOM overlays, not part of the app, and are faded after each line.
- The demo writes real demo documents to the target it records: two orders, one
  invoice, one payment, one credit note, one production run, two overheads, and
  (through the API, because the app has no purchase screen) two stock receipts
  so the production take has material and packaging. It never resets, edits or
  deletes existing data, and it only uses the seeded demo logins.
- The app does not invalidate the Leakage Radar query when an overhead is added,
  so scene 16 reloads the run page once to show the bridge with its overhead
  step rather than a stale chart.
- The Benchmark Console screen is not routed in this build (`/benchmark` is not
  in `frontend/src/App.tsx` / `Layout.tsx`), so the closing captions mention the
  `make benchmark` harness instead of showing a screen.
- Headless Chromium cannot display a PDF tab inside the recording, so scene 9
  fetches the PDF from the API, renders page 1 with `pdftoppm` and shows it as
  an image with a caption saying so.
- The MP4 is trimmed at the tail (closing card) to land at 7:57; the untrimmed
  master stays in `videos/kadai-demo.webm`.
- A fresh `make seed` reproduces the benchmark numbers (flour 43.125 → 31.14).
  The recorded instance had already been through earlier takes, so its weighted
  average is 44.76 and its cost per packet 31.49; the video shows its real
  numbers.
