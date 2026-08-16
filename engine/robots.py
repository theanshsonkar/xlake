"""Backward-compatible import/CLI facade for :mod:`core.robots`."""
from core.robots import *  # noqa: F401,F403


if __name__ == "__main__":
    import runpy
    runpy.run_module("core.robots", run_name="__main__")
