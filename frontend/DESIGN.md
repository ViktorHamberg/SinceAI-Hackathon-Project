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
- Hover updates only when the quarter changes. Step 4 shares that selection within
  ForecastAnalysis; App/table remain separate. There is no inspection animation or extra API call.
- Vertical touch swipes continue page scrolling. A tap selects the touched period;
  Left/Right/Home/End give the same choice through one keyboard tab stop.
- The plotting library is a separate lazy-loaded chunk. The table remains available
  during loading or chart failure. No data is copied into the build or fallback UI.

## Step 3B replay direction and decisions

The user requested a modern dragging interaction in the existing company-inspired
theme. Retain ENERGY 1 / RHYTHM 2 / MOTION 1: movement directly chooses a historical
issue time; no decorative animation, new imagery, neon palette or fake live feed.

- A native range handle and orange/brown elapsed segment form the replay gesture.
  Actual UTC date spacing preserves gaps between the six available forecasts.
- Nearby markers intentionally cluster. A native exact-time list and forecast
  navigation buttons provide precise alternatives rather than distorting time spacing.
- Preview is local to the selector so dragging does not rerender the chart/table or
  create requests. A prominent date readout distinguishes preview from displayed issue
  time; release commits the nearest available forecast, including when released outside
  the handle through pointer capture. Cancellation leaves the committed view unchanged.
- The new issue-time panel sits above context/chart. Its explicit forecast labels
  distinguish origin selection from the chart's delivery-quarter inspection controls.
- Controls stack on narrow screens; dates keep full timezone offsets, and the native
  list handles closely spaced and repeated local times through UTC-valued options.
- Selected snapshots clear during loading/error, share one identity check and update
  context/chart/table together. New origins reset quarter inspection and table scrolling.

## Step 4 probability and summary decisions

Keep the established ENERGY 1 / RHYTHM 2 / MOTION 1 and company palette. The supplied
inspiration images are references for clear groupings and aligned timelines, not an
instruction to add multiple interval bands, observed outcomes, a buy meter or a redesign.

- A compact summary group answers which delivery quarters have the highest predicted
  exceptional-price probabilities and widest interval. Matching metric structure makes
  these comparisons readable; each result links to actual returned quarters.
- Up/down/none and high/low events get separate probability panels to preserve their
  meanings. Fixed 0–100% axes and matching time geometry aid comparison with prices.
- Brown, charcoal and muted strokes reuse the palette; solid/dashed/dotted styles
  distinguish categories without treating colors as danger or trade recommendations.
- Shared quarter inspection is the only movement. Native exact selection and details
  preserve access if plotting fails. No animations, new assets or external services.
- Flat signals and tied maxima are stated explicitly, including the current persistence
  baseline. Summary labels are per-quarter and descriptive; no horizon-event probability,
  causal story or arbitrary alert threshold is inferred.

## Step 5B retrospective comparison decisions

- Keep the existing palette, typography and motion settings. The pressed Show actual
  outcomes button beside the price heading makes revealing later information deliberate.
- Observed prices use a darker brown dash-dot line, an explicit retrospective legend
  and an outlined inspection marker, distinguishing them from the solid median and
  pale uncertainty band without relying on color alone. No new visual assets are needed.
- The compact comparison strip below the price chart groups window metrics and exact
  selected-quarter outcomes. It remains usable if plotting fails. Probability panels
  retain their forecast-only meaning; no outcome enters their data or calculations.
- Missing actual prices create gaps. A terminal segment completes each observed quarter
  before a gap or the window end; the chart never invents a 41st record. The price axis
  includes observed extremes to avoid hiding errors outside the forecast interval.
- Controls and metric groups wrap at narrow widths. Existing keyboard inspection and
  timezone controls also govern the selected outcome, without another outcome request.
