# Project skills

These are project-scoped copies of Matt Pocock's skills, installed from
https://github.com/mattpocock/skills at commit
`4ae2317ddb22b046e26455e4f9c9b3aaaf62212d`.
The upstream MIT licence is preserved in `LICENSE.mattpocock-skills`.

## Installed skills

- `wayfinder`: plan a large effort as a map of decisions and investigations.
- `setup-matt-pocock-skills`: reconfigure tracker and domain-document conventions.
- `grilling`: clarify decisions with the user.
- `domain-modeling`: maintain shared terminology and significant design decisions.
- `research`: investigate questions using primary sources.
- `prototype`: build small prototypes to answer design questions.

The supporting skills and their reference files are included because Wayfinder
uses them. Each skill retains its upstream `SKILL.md` and `agents/openai.yaml`.
Keep these files in version control. This installation copies files into this
repository; it does not automatically update them or install a global plugin.
Avoid also enabling the same skills through a plugin in the same session.

## Use in Codex

In Codex CLI or the IDE extension, explicitly invoke `$wayfinder`, or select it
from `/skills`. For example:

```text
$wayfinder Plan our Finnish imbalance-price forecasting solution using this repository's local Markdown tracker.
```

Wayfinder and the setup skill require explicit invocation. Their Codex YAML
files set `allow_implicit_invocation: false`.

When an upstream instruction says to call the "Skill tool", use that tool if
the host provides it. In Codex sessions without that tool, load the named
supporting skill by reading its `SKILL.md` and follow its instructions with the
available tools. Read referenced files when needed. The wording does not require
Claude Code or installation of a separate Skill executable.

Local tracker and domain-document conventions are already recorded in
`../docs/agents/issue-tracker.md` and `../docs/agents/domain.md`. Re-run the setup
skill only if you want to change these conventions. Wayfinder plans the work;
invoke it separately when ready to begin planning.
