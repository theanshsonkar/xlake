"""Backward-compatible import/CLI facade for :mod:`core.pagetext`."""
from core.pagetext import *  # noqa: F401,F403


if __name__ == "__main__":
    import runpy
    runpy.run_module("core.pagetext", run_name="__main__")
