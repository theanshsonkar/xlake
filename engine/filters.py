"""Backward-compatible import/CLI facade for :mod:`core.filters`.

Library implementations are owned by ``core``; this file contains no copy.
"""
from core.filters import *  # noqa: F401,F403


if __name__ == "__main__":
    import runpy
    runpy.run_module("core.filters", run_name="__main__")
