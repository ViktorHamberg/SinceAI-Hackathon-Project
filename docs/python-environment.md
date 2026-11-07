# Shared Python environment: macOS and Windows

Use one local `.venv` per checkout for both the backend and forecasting engine, with
Python 3.12 and uv. Each teammate has their own environment; never share `.venv` through
Git. Frontend/npm setup is separate. No containers, workspaces or custom install scripts
are needed. Run all commands below from the repository root.

**Verification status:** The initial lock was generated and synced on macOS with
Python 3.12.15, pandas 2.2.3, NumPy 2.3.5 and FastAPI 0.162.2. The environment is
isolated (`include-system-site-packages = false`), all 31 installed packages pass
`uv pip check`, and a repeated offline sync dry run reports no changes. All 134 tests
passed: 33 package-local, 74 existing engine and 27 backend, including HTTP tests.
Windows execution remains unverified; the Windows developer must sync the same lock
and run the checks below. Universal marker handling was checked with a synthetic-package
Windows-target dry run, which does not verify this project's installation on Windows.
The initial PyPI access
problem was resolved by generating the lock in the user's network-enabled terminal.

## One-time setup

Install uv using its [official installation instructions](https://docs.astral.sh/uv/getting-started/installation/).
It is already installed on the development Mac. For a new checkout without `.venv`,
create a project environment. If `.venv` already exists, read the reuse/migration
instructions below before running this command:

```bash
uv venv --python 3.12 .venv
```

uv uses an available Python 3.12 or can download one. If `.venv` already exists with
Python 3.12 and `include-system-site-packages = false` in `.venv/pyvenv.cfg`, reuse it.
Do not recreate it after every pull. If an old environment inherits host packages
(`include-system-site-packages = true`), do not run an exact sync into it and claim
isolation. This was the original Mac setup; it has now been migrated. For any other
checkout needing that migration, stop running Python processes, deactivate it, and
preserve the old environment before replacing it:

macOS:

```bash
mkdir -p baseline_output
mv .venv baseline_output/python-env-before-uv
uv venv --python 3.12 .venv
```

Windows PowerShell, only if replacing an existing environment:

```powershell
New-Item -ItemType Directory -Force baseline_output | Out-Null
Move-Item .venv baseline_output/python-env-before-uv
uv venv --python 3.12 .venv
```

Use a different backup name if it already exists. Do not use the moved environment
in place; restoring it to `.venv` restores its original paths. Then sync as below.
The Mac's original environment was preserved at that backup location by the user.

## After pulling: same command on both operating systems

```bash
uv pip sync --python .venv requirements-dev.lock
uv pip check --python .venv
```

The first command installs the locked environment, including the engine in editable
mode, so source changes are available immediately. No separate `pip install -e .`,
backend install or activation is needed. It removes undeclared packages from the
project environment; add needed tools to declarations rather than installing them
manually and expecting them to survive sync. It does not manage system Python.

uv reuses installed compatible packages and its machine-local download/build cache;
it does not download the engine and backend's shared dependencies twice. First setup,
new versions and different OS wheels still need downloads. The cache is not committed
or copied between teammates. See [uv caching](https://docs.astral.sh/uv/concepts/cache/).

Do not substitute `uv sync` or `uv run` here: this setup uses uv's pip interface and a
requirements lock, not a uv project lock. Run code with the project interpreter:

| Platform | Python command |
|---|---|
| macOS | `.venv/bin/python` |
| Windows | `.\.venv\Scripts\python.exe` |

Configure your IDE to use that interpreter. Keep `.venv` and generated data ignored.

## Adding or changing a dependency

| Owner | Source of truth |
|---|---|
| Engine | `pyproject.toml`: core dependencies; future optional `ml` extra |
| Backend | `backend/requirements.txt`: existing backend pins |
| Shared development tools and migration constraints | `requirements-dev.in` |
| Starter package | Original `requirements.txt`, preserved unchanged |
| Resolved environment | Generated `requirements-dev.lock`, shared through Git |

The combined input currently pins pandas 2.2.3 and NumPy 2.3.5 to preserve the verified
engine versions during migration. Changing those constraints is an explicit upgrade
requiring regeneration and compatibility checks; don't loosen them just to pick the
latest versions. Engine package metadata retains its supported dependency ranges.

Edit the owning declaration, then regenerate the combined lock:

```bash
uv pip compile requirements-dev.in --python-version 3.12 --universal -o requirements-dev.lock
```

This also reads both requirements files and editable engine metadata. The universal
resolution retains environment markers for platform-specific packages, rather than
freezing only the Mac's installed packages. Existing lock pins are reused unless a
declaration requires a change; avoid broad `--upgrade`. Never hand-edit lock entries.
Resolve conflicting declarations and regenerate instead of combining conflicting
lock hunks. See [uv locking and syncing](https://docs.astral.sh/uv/pip/compile/).

Sync, test, and include both the changed declaration and regenerated lock in the same
review candidate. After its separately authorized merge/push, the other developer
pulls and syncs; they do not regenerate the lock merely because they pulled. Dependency
setup is shared work: announce changes, compatibility impact and required action before
adoption, following the roadmap's cross-boundary protocol. Test Windows on Windows;
a universal resolution alone is not execution verification on both OSes.

LightGBM is not added or installed by this setup. When Step 2 and its dependency are
approved, declare its optional extra in `pyproject.toml`, change `-e .` here to
`-e .[ml]`, regenerate the combined lock and verify both OSes/native prerequisites.
Do not add it separately to backend requirements. No forecasting interface changes
are needed for package synchronization.

## Checks before sharing dependency changes

```bash
uv pip check --python .venv
```

Then run these with the project Python command for your OS:

```text
-W error::FutureWarning -m unittest discover -s src/forecast_engine/tests -t src -v
-W error::FutureWarning -m unittest discover -s tests -v
-W error::FutureWarning -m unittest discover -s backend/tests -t . -v
```

Report all results and environment limits in the independent-review handoff. Don't
claim the app is compatible if required HTTP packages couldn't be installed/tested.
An unavailable network or unresolved version is a setup blocker: retain the working
environment, report it, and do not fabricate a lock or silently change backend pins.

The legacy pip installation examples in older guides describe earlier acceptance
environments. Use this single sync workflow for ongoing team development. After
dependency review approval, obtain separate authorization before committing or pushing
the declarations and lock; neither synchronization nor passing tests grants it.
