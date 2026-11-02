"""A support ticket inbox, the second environment (D21, D22).

Same shape as the calendar env: data rebuilt on every reset, tools that refuse
unknown ids with UnknownIdError, and a state check that compares the final data
with the initial data field by field, so collateral changes are caught.

Every task comes in two variants that leave the same final state: one names the
ticket and agent by id, the other only by customer, subject and agent name, so
the agent must look them up. The pairs measure the id vs name gap.
"""

from __future__ import annotations

import copy
import json

from ..env import Environment, Param, Task, ToolError, ToolSpec, UnknownIdError, seeded
from ..types import Action

SEED = {
    "agents": [
        {"id": "agt_01", "name": "Priya Shah"},
        {"id": "agt_02", "name": "Marco Rossi"},
        {"id": "agt_03", "name": "Lena Park"},
    ],
    "tickets": [
        {"id": "T-1001", "subject": "Refund not received", "customer": "Dana Lee",
         "status": "open", "priority": "normal", "assignee_id": ""},
        {"id": "T-1002", "subject": "Login loop on mobile", "customer": "Bob Ortiz",
         "status": "open", "priority": "normal", "assignee_id": "agt_02"},
        # Same subject as T-1002 from another customer: a trap for "close the login loop ticket".
        {"id": "T-1003", "subject": "Login loop on mobile", "customer": "Ana Gomez",
         "status": "open", "priority": "normal", "assignee_id": ""},
        {"id": "T-1004", "subject": "Invoice has wrong VAT", "customer": "Dana Lee",
         "status": "closed", "priority": "normal", "assignee_id": "agt_01"},
        # Same subject as T-1001 from another customer: a trap for "Dana's refund ticket".
        {"id": "T-1005", "subject": "Refund not received", "customer": "Kim Novak",
         "status": "open", "priority": "high", "assignee_id": "agt_03"},
    ],
}

STATUSES = ("open", "closed")
PRIORITIES = ("low", "normal", "high")


def expect_changes(changes: dict[str, dict]):
    """Build a state check: exactly these ticket fields change to these values, nothing else."""
    want = {tid: dict(fields) for tid, fields in changes.items()}

    def check(initial: dict, final: dict) -> list[str]:
        problems = []
        before = {t["id"]: t for t in initial["tickets"]}
        after = {t["id"]: t for t in final["tickets"]}
        for tid in sorted(set(before) - set(after)):
            problems.append(f"ticket {tid} was removed")
        for tid in sorted(set(after) - set(before)):
            problems.append(f"unexpected new ticket {tid}")
        for tid in sorted(set(before) & set(after)):
            target = {**before[tid], **want.get(tid, {})}
            for key in sorted(set(target) | set(after[tid])):
                got, exp = after[tid].get(key), target.get(key)
                if got == exp:
                    continue
                if key in want.get(tid, {}):
                    problems.append(f"{tid} {key} is {got!r}, expected {exp!r}")
                else:
                    problems.append(f"unexpected change to {tid} {key}: "
                                    f"{before[tid].get(key)!r} -> {got!r}")
        for tid in sorted(set(want) - set(before)):
            problems.append(f"check refers to unknown ticket {tid}")
        if initial["agents"] != final["agents"]:
            problems.append("agents changed")
        return problems

    return check


def _a(tool: str, **arguments) -> Action:
    return Action(tool, arguments)


TASKS = {t.id: t for t in [
    Task(
        id="assign_by_id",
        prompt="Assign ticket T-1001 to agent agt_01.",
        reference=[_a("assign_ticket", ticket_id="T-1001", agent_id="agt_01")],
        check=expect_changes({"T-1001": {"assignee_id": "agt_01"}}),
        tags=("assign", "explicit id"), pair="assign", variant="id",
    ),
    Task(
        id="assign_by_name",
        prompt="Assign Dana Lee's ticket about the refund she has not received to Priya Shah.",
        reference=[_a("list_agents"),
                   _a("search_tickets", query="Dana Lee"),
                   _a("assign_ticket", ticket_id="T-1001", agent_id="agt_01")],
        check=expect_changes({"T-1001": {"assignee_id": "agt_01"}}),
        tags=("assign", "name lookup", "same subject"), pair="assign", variant="name",
    ),
    Task(
        id="close_by_id",
        prompt="Set the status of ticket T-1002 to closed.",
        reference=[_a("set_status", ticket_id="T-1002", status="closed")],
        check=expect_changes({"T-1002": {"status": "closed"}}),
        tags=("close", "explicit id"), pair="close", variant="id",
    ),
    Task(
        id="close_by_name",
        prompt=("Close Bob Ortiz's ticket about the login loop on mobile. Other tickets with "
                "the same subject must stay open."),
        reference=[_a("search_tickets", query="login loop"),
                   _a("set_status", ticket_id="T-1002", status="closed")],
        check=expect_changes({"T-1002": {"status": "closed"}}),
        tags=("close", "name lookup", "same subject"), pair="close", variant="name",
    ),
    Task(
        id="escalate_by_id",
        prompt="Set the priority of ticket T-1003 to high and assign it to agent agt_03.",
        reference=[_a("set_priority", ticket_id="T-1003", priority="high"),
                   _a("assign_ticket", ticket_id="T-1003", agent_id="agt_03")],
        check=expect_changes({"T-1003": {"priority": "high", "assignee_id": "agt_03"}}),
        tags=("escalate", "explicit id", "two writes"), pair="escalate", variant="id",
    ),
    Task(
        id="escalate_by_name",
        prompt=("Ana Gomez's login ticket is urgent: make it high priority and give it to "
                "Lena Park."),
        reference=[_a("list_agents"),
                   _a("search_tickets", query="Ana Gomez"),
                   _a("set_priority", ticket_id="T-1003", priority="high"),
                   _a("assign_ticket", ticket_id="T-1003", agent_id="agt_03")],
        check=expect_changes({"T-1003": {"priority": "high", "assignee_id": "agt_03"}}),
        tags=("escalate", "name lookup", "two writes"), pair="escalate", variant="name",
    ),
]}


class InboxEnv(Environment):
    name = "inbox"
    description = ("It holds support agents (id and name) and tickets (id like T-1001, "
                   "subject, customer, status open or closed, priority low, normal or high, "
                   "assignee_id, empty when unassigned).")
    tasks = TASKS

    def seed_data(self, seed: int | None) -> dict:
        # A seed shuffles agents and tickets, so search results come back in another order (D25).
        data = copy.deepcopy(SEED)
        seeded(data, seed, ("agents", "tickets"))
        return data

    def tool_specs(self) -> dict[str, ToolSpec]:
        tid = Param("string", "Ticket id, for example T-1001.")
        return {s.name: s for s in [
            ToolSpec("list_agents", "List all support agents with their id and name.", {},
                     self._list_agents, read_only=True),
            ToolSpec("search_tickets", "Find tickets whose subject or customer contains the "
                     "query (case insensitive), optionally only one status.",
                     {"query": Param("string", "Text to look for, for example a customer name."),
                      "status": Param("string", "Optional: open or closed.", required=False)},
                     self._search_tickets, read_only=True),
            ToolSpec("assign_ticket", "Assign a ticket to an agent.",
                     {"ticket_id": tid,
                      "agent_id": Param("string", "Agent id, for example agt_01.")},
                     self._assign_ticket),
            ToolSpec("set_status", "Set a ticket's status.",
                     {"ticket_id": tid, "status": Param("string", "open or closed.")},
                     self._set_status),
            ToolSpec("set_priority", "Set a ticket's priority.",
                     {"ticket_id": tid, "priority": Param("string", "low, normal or high.")},
                     self._set_priority),
        ]}

    # ----- lookups that raise -----
    def _ticket(self, ticket_id: str) -> dict:
        for t in self.data["tickets"]:
            if t["id"] == ticket_id:
                return t
        raise UnknownIdError(f"no ticket with id '{ticket_id}'. Use search_tickets to find ids.")

    def _agent(self, agent_id: str) -> dict:
        for a in self.data["agents"]:
            if a["id"] == agent_id:
                return a
        raise UnknownIdError(f"no agent with id '{agent_id}'. Use list_agents to find ids.")

    # ----- tools -----
    def _list_agents(self) -> str:
        return json.dumps(self.data["agents"])

    def _search_tickets(self, query: str, status: str = "") -> str:
        q = query.strip().lower()
        if not q:
            raise ToolError("query must not be empty")
        if status and status not in STATUSES:
            raise ToolError(f"status must be one of {', '.join(STATUSES)}, got {status!r}")
        found = [t for t in self.data["tickets"]
                 if (q in t["subject"].lower() or q in t["customer"].lower())
                 and (not status or t["status"] == status)]
        return json.dumps(found)

    def _assign_ticket(self, ticket_id: str, agent_id: str) -> str:
        t = self._ticket(ticket_id)
        a = self._agent(agent_id)
        t["assignee_id"] = a["id"]
        return f"assigned {t['id']} to {a['id']} ({a['name']})"

    def _set_status(self, ticket_id: str, status: str) -> str:
        t = self._ticket(ticket_id)
        if status not in STATUSES:
            raise ToolError(f"status must be one of {', '.join(STATUSES)}, got {status!r}")
        t["status"] = status
        return f"{t['id']} status is {status}"

    def _set_priority(self, ticket_id: str, priority: str) -> str:
        t = self._ticket(ticket_id)
        if priority not in PRIORITIES:
            raise ToolError(f"priority must be one of {', '.join(PRIORITIES)}, got {priority!r}")
        t["priority"] = priority
        return f"{t['id']} priority is {priority}"
