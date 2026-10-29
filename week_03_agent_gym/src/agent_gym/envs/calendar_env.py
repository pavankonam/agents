"""A small calendar environment, after Turing's Calendar Gym on OpenEnv (D2).

All data is in memory and rebuilt on every reset, so episodes never leak into
each other. Tasks are checked by comparing the final data with the initial data
(D7): the expected events must exist and nothing else may have changed.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import re

from ..env import Environment, Param, Task, ToolError, ToolSpec
from ..types import Action

SEED = {
    "calendars": [
        {"id": "cal_team", "name": "Team"},
        {"id": "cal_personal", "name": "Personal"},
        {"id": "cal_oncall", "name": "On-call"},
    ],
    "events": [
        {"id": "evt_001", "calendar_id": "cal_team", "title": "Standup",
         "date": "2026-11-02", "start": "09:00", "end": "09:15"},
        {"id": "evt_002", "calendar_id": "cal_team", "title": "Old sync",
         "date": "2026-11-02", "start": "14:00", "end": "15:00"},
        {"id": "evt_003", "calendar_id": "cal_personal", "title": "Gym",
         "date": "2026-11-03", "start": "07:00", "end": "08:00"},
        # Same title as evt_002 one week later: a trap for "cancel Old sync" (D9).
        {"id": "evt_004", "calendar_id": "cal_team", "title": "Old sync",
         "date": "2026-11-09", "start": "14:00", "end": "15:00"},
    ],
}

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _key(e: dict) -> tuple:
    return (e["calendar_id"], e["title"].strip().lower(), e["date"], e["start"], e["end"])


def _show(e: dict) -> str:
    return f"{e['title']!r} on {e['calendar_id']} {e['date']} {e['start']}-{e['end']}"


def expect(added: list[dict] | None = None, removed: list[str] | None = None):
    """Build a state check: exactly these events added and these ids removed, nothing else."""
    want = list(added or [])
    want_added = sorted(_key(e) for e in want)
    want_removed = sorted(removed or [])

    def check(initial: dict, final: dict) -> list[str]:
        problems = []
        before = {e["id"]: e for e in initial["events"]}
        after = {e["id"]: e for e in final["events"]}
        new = [after[i] for i in after if i not in before]
        gone = sorted(i for i in before if i not in after)
        changed = sorted(i for i in before if i in after and before[i] != after[i])
        new_keys = sorted(_key(e) for e in new)
        for e in want:
            if _key(e) not in new_keys:
                problems.append("missing event: " + _show(e))
        for e in new:
            if _key(e) not in want_added:
                problems.append("unexpected new event: " + _show(e))
        for i in want_removed:
            if i not in gone:
                problems.append(f"event {i} should have been deleted")
        for i in gone:
            if i not in want_removed:
                problems.append(f"unexpected deletion: {i} ({_show(before[i])})")
        for i in changed:
            problems.append(f"unexpected change to {i}")
        if initial["calendars"] != final["calendars"]:
            problems.append("calendars changed")
        return problems

    return check


def _ev(cal, title, date, start, end):
    return {"calendar_id": cal, "title": title, "date": date, "start": start, "end": end}


TASKS = {t.id: t for t in [
    Task(
        id="create_explicit",
        prompt=("On calendar cal_team, create an event titled 'Design review' on 2026-11-02 "
                "from 10:00 to 10:30."),
        reference=[Action("create_event", _ev("cal_team", "Design review", "2026-11-02",
                                              "10:00", "10:30"))],
        check=expect(added=[_ev("cal_team", "Design review", "2026-11-02", "10:00", "10:30")]),
        tags=("create", "explicit id"),
    ),
    Task(
        id="create_by_name",
        prompt=("Add a one hour event called 'Dentist' to my Personal calendar on 2026-11-03 "
                "starting at 15:00."),
        reference=[Action("list_calendars", {}),
                   Action("create_event", _ev("cal_personal", "Dentist", "2026-11-03",
                                              "15:00", "16:00"))],
        check=expect(added=[_ev("cal_personal", "Dentist", "2026-11-03", "15:00", "16:00")]),
        tags=("create", "name lookup"),
    ),
    Task(
        id="delete_by_title",
        prompt=("Cancel the 'Old sync' meeting on the Team calendar on 2026-11-02. "
                "Leave everything else as it is."),
        reference=[Action("list_calendars", {}),
                   Action("list_events", {"calendar_id": "cal_team", "date": "2026-11-02"}),
                   Action("delete_event", {"event_id": "evt_002"})],
        check=expect(removed=["evt_002"]),
        tags=("delete", "name lookup", "ambiguous title"),
    ),
    Task(
        id="first_free_slot",
        prompt=("Book a one hour 'Retro' on the Team calendar on 2026-11-02 at the first full "
                "hour from 14:00 onwards that does not overlap another Team event."),
        reference=[Action("list_calendars", {}),
                   Action("list_events", {"calendar_id": "cal_team", "date": "2026-11-02"}),
                   Action("create_event", _ev("cal_team", "Retro", "2026-11-02",
                                              "15:00", "16:00"))],
        check=expect(added=[_ev("cal_team", "Retro", "2026-11-02", "15:00", "16:00")]),
        tags=("create", "name lookup", "reasoning"),
    ),
]}


class CalendarEnv(Environment):
    name = "calendar"
    description = ("It holds calendars (id and name) and events (id, calendar_id, title, "
                   "date YYYY-MM-DD, start and end HH:MM, 24 hour clock).")
    tasks = TASKS

    def seed_data(self, seed: int | None) -> dict:
        # seed is accepted for the OpenEnv shaped API; day 1 data is fixed.
        self._next_id = 101
        return copy.deepcopy(SEED)

    def tool_specs(self) -> dict[str, ToolSpec]:
        return {s.name: s for s in [
            ToolSpec("list_calendars", "List all calendars with their id and name.", {},
                     self._list_calendars),
            ToolSpec("list_events", "List events of one calendar, optionally on one date.",
                     {"calendar_id": Param("string", "Calendar id, for example cal_team."),
                      "date": Param("string", "Optional date YYYY-MM-DD.", required=False)},
                     self._list_events),
            ToolSpec("create_event", "Create an event. Fails if it overlaps another event "
                     "on the same calendar.",
                     {"calendar_id": Param("string", "Calendar id."),
                      "title": Param("string", "Event title."),
                      "date": Param("string", "Date YYYY-MM-DD."),
                      "start": Param("string", "Start time HH:MM."),
                      "end": Param("string", "End time HH:MM, after start.")},
                     self._create_event),
            ToolSpec("delete_event", "Delete one event by its id.",
                     {"event_id": Param("string", "Event id, for example evt_001.")},
                     self._delete_event),
        ]}

    # ----- tools -----
    def _calendar(self, calendar_id: str) -> dict:
        for c in self.data["calendars"]:
            if c["id"] == calendar_id:
                return c
        ids = ", ".join(c["id"] for c in self.data["calendars"])
        raise ToolError(f"no calendar with id '{calendar_id}' (ids: {ids}). "
                        "Use list_calendars to find ids.")

    def _list_calendars(self) -> str:
        return json.dumps(self.data["calendars"])

    def _list_events(self, calendar_id: str, date: str = "") -> str:
        self._calendar(calendar_id)
        if date:
            _check_date(date)
        events = [e for e in self.data["events"] if e["calendar_id"] == calendar_id
                  and (not date or e["date"] == date)]
        events.sort(key=lambda e: (e["date"], e["start"]))
        return json.dumps(events)

    def _create_event(self, calendar_id: str, title: str, date: str, start: str,
                      end: str) -> str:
        self._calendar(calendar_id)
        if not title.strip():
            raise ToolError("title must not be empty")
        _check_date(date)
        for name, value in (("start", start), ("end", end)):
            if not TIME_RE.match(value):
                raise ToolError(f"{name} must be HH:MM (24 hour), got {value!r}")
        if end <= start:
            raise ToolError(f"end {end} must be after start {start}")
        for e in self.data["events"]:
            if (e["calendar_id"] == calendar_id and e["date"] == date
                    and start < e["end"] and e["start"] < end):
                raise ToolError(f"overlaps {e['id']} {_show(e)}")
        event = {"id": f"evt_{self._next_id}", **_ev(calendar_id, title.strip(), date,
                                                       start, end)}
        self._next_id += 1
        self.data["events"].append(event)
        return f"created {event['id']}"

    def _delete_event(self, event_id: str) -> str:
        for i, e in enumerate(self.data["events"]):
            if e["id"] == event_id:
                del self.data["events"][i]
                return f"deleted {event_id} ({_show(e)})"
        raise ToolError(f"no event with id '{event_id}'. Use list_events to find ids.")


def _check_date(value: str) -> None:
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        raise ToolError(f"date must be YYYY-MM-DD, got {value!r}") from None
    if len(value) != 10:
        raise ToolError(f"date must be YYYY-MM-DD, got {value!r}")
