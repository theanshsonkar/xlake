"""Backward-compatible import/CLI facade for :mod:`core.cache`."""
from core.cache import *  # noqa: F401,F403


if __name__ == "__main__":
    import runpy
    runpy.run_module("core.cache", run_name="__main__")
