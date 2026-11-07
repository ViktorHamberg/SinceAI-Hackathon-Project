"""Enable python -m forecast_engine without adding import-time execution."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
