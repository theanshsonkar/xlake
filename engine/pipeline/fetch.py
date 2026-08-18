"""Backward-compatible facade for :mod:`adapters.boards`.

The implementation lives in ``adapters/boards.py``. This launcher keeps
existing ``import fetch`` callers and ``python3 fetch.py ...`` usage working.
"""
from adapters.boards import *  # noqa: F401,F403
from adapters.boards import _release, _request, _throttle, main


if __name__ == "__main__":
    main()
