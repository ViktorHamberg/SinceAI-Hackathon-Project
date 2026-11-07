# Forecast workspace design

Direction comes from the user's Turku Energia website reference: white, charcoal,
restrained warm orange, simple navigation and strong functionality for energy experts.
This is a challenge workspace, not an official company product or a copy of its site.

Design read: a historical forecasting workspace for energy experts, with a compact
working layout. ENERGY 1 / RHYTHM 2 / MOTION 1.

- Color: orange connects to the supplied company reference; charcoal carries readable
  controls and text. A quiet warm neutral separates the workspace from white data surfaces.
- Layout: forecast origin and delivery end sit directly above the table because those
  times determine what the expert is reviewing. Technical identity stays in details.
- Typography: native system sans fonts keep dense numbers readable on Windows/macOS
  without a font download. Tabular figures align prices; monospace is reserved for IDs.
- Spacing: compact working rows give the forecast priority; larger gaps separate the
  context, data and provenance instead of giving every element the same weight.
- Accent: the origin strip identifies the selected historical context; the pale median
  column directs scanning to P50. Labels and font weight carry the same meaning in monochrome.
- Controls: 44px minimum hit areas, native buttons/details, visible keyboard focus,
  explicit selected-timezone state and persistent reload preserve predictable operation.
- Time: Helsinki is the default. The visible UTC switch changes presentation only,
  including metadata, and never changes UTC identifiers, values or the requested forecast.
- Responsive layout: one context column on narrow screens, two plus model at intermediate
  widths, three on wide screens. Wide price data scrolls inside a named keyboard region.
- Motion: no decorative or continuous animation; hover, press and focus communicate
  interaction without movement. No dark theme or toggle is shipped.
- Content: genuine API forecast values only. The UI identifies historical replay and
  the persistence baseline, keeps actual outcomes separate and makes no accuracy claim.
- Assets: reuse the existing local favicon; no new logo, illustration, photo or external
  image is created for this redesign. The company name is plain text with challenge context.

Verification and remaining limits belong in the roadmap and independent-review handoff.

## Step 2B chart decisions

- The chart answers how the median and uncertainty vary across the ten-hour delivery
  window. Its placement above exact values makes the overview the first data view.
- The charcoal median and warm shaded interval follow the supplied company direction.
  Solid versus dashed boundaries and explicit labels distinguish the series without hue.
- Step-after geometry represents the actual quarter-hour periods, with the final
  interval drawn to its delivery end. There is no smoothing or extra forecast row.
- The selected-delivery strip replaces floating tooltips so small screens can show
  complete dates, offsets and exact prices without covering the data being inspected.
- React owns one selection index for mouse, tap and keyboard. Recharts supplies plotting
  and resize behavior; its built-in interaction layer is disabled to avoid competing
  selection states. Shared plot dimensions keep hit-testing aligned with the axes.
- Hover updates only this chart component, only when the quarter changes. There is no
  inspection animation, no per-pointer update to the App/table and no extra HTTP call.
- Vertical touch swipes continue page scrolling. A tap selects the touched period;
  Left/Right/Home/End give the same choice through one keyboard tab stop.
- The plotting library is a separate lazy-loaded chunk. The table remains available
  during loading or chart failure. No data is copied into the build or fallback UI.
