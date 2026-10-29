"""Shipped environments, by name."""

from .calendar_env import CalendarEnv

ENVIRONMENTS = {CalendarEnv.name: CalendarEnv}

__all__ = ["CalendarEnv", "ENVIRONMENTS"]
