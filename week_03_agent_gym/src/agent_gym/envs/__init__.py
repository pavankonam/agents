"""Shipped environments, by name."""

from .calendar_env import CalendarEnv
from .inbox_env import InboxEnv

ENVIRONMENTS = {CalendarEnv.name: CalendarEnv, InboxEnv.name: InboxEnv}

__all__ = ["CalendarEnv", "ENVIRONMENTS", "InboxEnv"]
