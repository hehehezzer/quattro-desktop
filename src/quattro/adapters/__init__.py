"""Stable adapter boundary backed by Quattro's mature adapters."""

from quattro_agent.adapters import AgentAdapter, CodexAdapter, PiAdapter, adapter_for
from quattro_agent.omniroute import OmniRouteContract

__all__ = ["AgentAdapter", "CodexAdapter", "PiAdapter", "adapter_for", "OmniRouteContract"]
