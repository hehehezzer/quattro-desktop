"""Quattro public package.

The mature orchestration implementation remains in :mod:`quattro_agent` for
CLI and import compatibility.  :mod:`quattro.core` is the stable product
boundary; it re-exports that implementation without duplicating it.
"""

from quattro_agent import *  # noqa: F401,F403
