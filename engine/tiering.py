"""Backward-compatible import/CLI facade for :mod:`core.tiering`."""
from core.tiering import *  # noqa: F401,F403


if __name__ == "__main__":
    import runpy
    runpy.run_module("core.tiering", run_name="__main__")
