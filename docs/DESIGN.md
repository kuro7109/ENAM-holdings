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

Contrast (WCAG AA): ink on paper 13.4:1; `--ink-2` on paper 6.6:1; `--ink-3` on paper 3.6:1
(used only for 12–13px meta, large-ish UI labels); blue on paper 7.9:1; white on ink 15.6:1.

**Type:** one family, Archivo (self-hosted). The width axis carries hierarchy: expanded for
the sentence that matters, normal for reading, condensed + tabular figures for numbers.

## Behaviour
- One passive `pointerdown` listener (`web/src/press.ts`): ripple from the touch point,
  `navigator.vibrate(4)` on taps and `8` on primary actions; **Done** gives a pop on the
  headline count and a firmer 15 ms buzz. All motion is off under `prefers-reduced-motion`.
- Screens enter with a fade and an 8px rise (220 ms); only transform and opacity animate.
- 44px minimum tap targets everywhere (chips, Done, links via padded hit areas, slider).
- Phone: bottom tab bar with labels, safe-area insets. Desktop (≥1024px): left sidebar.
- Loading, empty and error states on every data view (Brief, Holdings, Research).

## Audit (before → after)

| Check | 390px | 360px | 1440px |
|---|---|---|---|
| Horizontal overflow | none → none | none → none | none → none |
| Console errors | 0 → 0 | 0 → 0 | 0 → 0 |
| Tap targets < 44px | 27 → 0 | 27 → 0 | 27 → 0 |
| Press feedback | none → ripple + haptics | same | ripple |
| Desktop navigation | — | — | phone bottom bar → sidebar |

## Test list
Brief: window chips, Done (count drops, item leaves), Worth-a-look rows expand, Folded expands,
Open filing. Alerts: each dial updates the count and history live; σ on/off; category chips
persist after reload. Holdings: tap a stock → sheet → Research button opens that symbol.
Research: each ready chip loads; unknown symbol shows guidance; transcript links open at the page.
All at 360, 390 and 1440px.
