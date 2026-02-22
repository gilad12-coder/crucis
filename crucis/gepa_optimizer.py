"""Compatibility wrapper for the GEPA optimizer worker module path."""

from crucis.execution.optimizer import main

if __name__ == "__main__":
    raise SystemExit(main())
