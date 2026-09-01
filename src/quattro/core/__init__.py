"""Quattro Core: durable orchestration independent of desktop integrations.

This namespace intentionally delegates to the established ``quattro_agent``
implementation.  Existing callers keep their imports while new integrations
can depend on ``quattro.core``.  Desktop code is never imported here.
"""

from quattro_agent import *  # noqa: F401,F403
