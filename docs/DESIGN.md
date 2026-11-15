# FINN design notes

**Mood:** calm, exact, unhurried. A ledger page, not a trading terminal.

## Tokens (web/src/styles.css)

| Role | Token | Value | Use |
|---|---|---|---|
| 70% dominant | `--paper` | `#E9ECE4` | background (cool ledger paper) |
| 30% secondary | `--paper-2` / `--ink` | `#F4F6F0` / `#16233A` | raised sheets / text, tab bar |
| 10% accent | `--blue` | `#2443A8` | links and the one thing to press |
| Lines | `--rule` | `#C9CFC2` | ledger rules |
| Semantic | `--up` `--down` `--amber` | `#1E7A4B` `#B42318` `#8A5A00` | gains, losses / red flags, caution only |
| Motion | `--t-fast` `--t-med` `--t-slow` | 150 / 220 / 400 ms | hover / sheets and screens / hero |
| Easing | `--ease` `--spring` | `cubic-bezier(.2,.7,.2,1)` / `(.34,1.56,.64,1)` | default / success pop only |

Contrast (WCAG 2 formula, computed): ink on paper 13.2:1; `--ink-2` 6.3:1; `--ink-3` 4.7:1
(was 3.2:1, which failed AA for small text, so it was darkened from #7B8494 to #5F6878);
blue links 7.2:1; white on ink 15.7:1; tab labels on ink 7.7:1; gain green 4.9:1, loss red 6.0:1,
amber 5.4:1 on raised sheets. All pass AA for body text.

**Type:** one family, Archivo (self-hosted). The width axis carries hierarchy: expanded for
the sentence that matters, normal for reading, condensed + tabular figures for numbers.

## Behaviour
- `web/src/press.ts`: ripple from the touch point on `pointerdown`; haptics on `click`
  (Chrome blocks `navigator.vibrate` until a tap completes, so vibrating on pointerdown
  silently fails on the first tap). 4 ms on taps, 8 ms on primary buttons, 3 ms rate-limited
  ticks while dragging an alert dial, 15 ms + a pop on the headline count for **Done**.
  iPhone Safari has no vibrate API: on iOS 18+ a hidden native `<input switch>` is toggled
  inside the tap, which plays the system haptic. Motion is off under `prefers-reduced-motion`.
- Back button steps between tabs (each tab is a history entry); the stock sheet closes on
  Escape or a tap outside and locks the page behind it.
- Screens enter with a fade and an 8px rise (220 ms); only transform and opacity animate.
- 44px minimum tap targets everywhere (chips, Done, links via padded hit areas, slider).
- Phone: bottom tab bar with labels, safe-area insets. Desktop (≥1024px): left sidebar.
- Loading, empty and error states on every data view (Brief, Holdings, Research).

## Charts (web/src/components/Charts.tsx)
One y-axis per chart (sales and margin are two charts, never a dual axis); bars ≤24px with a
4px rounded data-end; 2px lines with a ringed end-dot; a readout line answers "what is this
mark?" on hover or tap; text uses text tokens, never the series colour. Two-series charts use
emphasis: the series the story is about in `--blue`, the reference in grey `#7B8494` (3.5:1;
validator: CVD ΔE 29.8 vs blue). Gains/losses keep green/red but always with direction and a
signed number, never colour alone.

| Where | Chart | Question it answers |
|---|---|---|
| Brief, results card | Year ago vs this quarter (revenue, PAT) | Is it bigger than a year ago? |
| Alerts | Stocks flagged per session, live with the dials | How noisy would these settings be? |
| Holdings | Six biggest moves, diverging from zero | What moved most at the close? |
| Research | Promise bullets (target band vs actual) | Did they hit what they guided? |
| Research | Quarterly sales; EBITDA margin (separate) | Is growth real, and is it profitable? |
| Research | Operating cash vs net profit by year | Is profit turning into cash? |
| Research | Debtor days | Is working capital getting worse? |
| Research home | Ranked bars across companies, 6 measures | Who keeps promises, grows, converts cash, costs least? |

## Audit (before → after)

| Check | 390px | 360px | 1440px |
|---|---|---|---|
| Horizontal overflow | none → none | none → none | none → none |
| Console errors | 0 → 0 | 0 → 0 | 0 → 0 |
| Tap targets < 44px | 27 → 0 | 27 → 0 | 27 → 0 |
| Press feedback | none → ripple + haptics | same | ripple |
| Desktop navigation | — | — | phone bottom bar → sidebar |
| Back button | left the app → steps between tabs | same | same |
| Haptics on first tap (Android) | blocked → fires | same | n/a |
| Haptics on iPhone | none → system haptic (iOS 18+) | same | n/a |

## Test list
Brief: window chips, Done (count drops, item leaves), Worth-a-look rows expand, Folded expands,
Open filing. Alerts: each dial updates the count and history live; σ on/off; category chips
persist after reload. Holdings: tap a stock → sheet → Research button opens that symbol.
Research: each ready chip loads; unknown symbol shows guidance; transcript links open at the page.
All at 360, 390 and 1440px.
