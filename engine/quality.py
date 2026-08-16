"""Backward-compatible import/CLI facade for :mod:`core.quality`."""
from core.quality import *  # noqa: F401,F403


if __name__ == "__main__":
    import runpy
    runpy.run_module("core.quality", run_name="__main__")
