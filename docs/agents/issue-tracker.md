# Issue tracker: local Markdown

Project planning lives in `.scratch/<effort>/` inside this repository. Creating
or updating a ticket means editing a local file. This configuration uses no
external issue tracker.

## Wayfinding operations

- Map: `.scratch/<effort>/map.md`, with Destination, Notes, Decisions so far,
  Not yet specified, and Out of scope sections as described by Wayfinder.
- Child ticket: `.scratch/<effort>/issues/NN-<slug>.md`, numbered from `01`.
  Use the relative file path as its identity and its title in human-facing links.
- Ticket metadata: `Type: research|prototype|grilling|task`,
  `Status: open|claimed|resolved|out-of-scope`, `Assignee: <name or empty>`,
  and `Blocked by: <comma-separated ticket numbers or none>`.
- A ticket is unblocked when all listed prerequisites are resolved. The frontier
  consists of open, unblocked tickets with no assignee, in numeric order.
- Claim a ticket by setting its assignee and `Status: claimed` before working.
- Append conversation under `## Comments`; record the resolved decision under
  `## Answer`, set `Status: resolved`, and link it from the map's Decisions so far.
- For work ruled out of scope, set `Status: out-of-scope` and link it from the
  map's Out of scope section. Revisit dependent tickets if their premise changes.
- Keep research notes and prototype references beside the effort, and link them
  from the relevant ticket. Record any research or prototype branch as a link;
  local planning does not require publishing a branch or creating remote issues.

Store specs at `.scratch/<effort>/spec.md` when needed. Create folders and tickets
as work arises. The triage skill is not installed, so no triage-label mapping is
needed. Apply the project's data and licence rules to every planning artifact.
