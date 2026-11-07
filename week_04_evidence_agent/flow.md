# Flow: Evidence Agent

Status: **Day 3**. Every box exists in the code.

```mermaid
flowchart TD
    CLI[python3 -m evidence_agent<br/>list, check, run SCENARIO<br/>--json --record PATH] --> RI
    QM[quiz/quiz_model.py<br/>reference run per scenario, must score 100,<br/>9 controls in --fake over 3 scenarios<br/>with support status and score,<br/>--record PATH] --> RI
    RI[run_investigation<br/>agent.py] -->|system prompt + question| M[LLM client.chat<br/>OllamaClient or FakeClient<br/>6 tools]
    M -->|text only| NC[finish no_conclusion]
    M -->|tool calls, in order| CALL{Investigation.call}
    CALL -->|unknown tool or<br/>validate_args fails| REF[refused step<br/>error back to model]
    CALL -->|list_services| SV[service names<br/>no evidence ids]
    CALL -->|search_logs, get_metric,<br/>list_deploys| Q[filter scenario records]
    Q --> LED[EvidenceLedger.issue<br/>ev_NNN by first sight,<br/>same record same id,<br/>only shown rows]
    LED --> ROWS["lines like [ev_003] 14:05 payments ERROR ..."]
    CALL -->|report_finding| CIT{citations ok?<br/>claim not empty,<br/>ids non empty,<br/>all issued by ledger}
    CIT -->|no| RF[finding kept with accepted=False<br/>error back to model]
    CIT -->|yes, no check| AF[finding accepted<br/>support unchecked]
    CIT -->|yes, with check| PC{parse_check<br/>keys, op aliases,<br/>number for > >= < <=,<br/>at is HH:MM}
    PC -->|bad| RF
    PC -->|ok| SUP{check_support<br/>cited rows only:<br/>same service, field,<br/>and at if given}
    SUP -->|a relevant row holds| AFS[finding accepted<br/>support supported<br/>backing ids]
    SUP -->|relevant rows, none holds| RF
    SUP -->|no relevant row| RF
    AFS --> LIM
    CALL -->|conclude| CC{service known,<br/>summary not empty,<br/>citations ok?}
    CC -->|no| REF
    CC -->|yes| END[finish concluded]
    REF --> LIM{steps >= max_steps?}
    SV --> LIM
    ROWS --> LIM
    RF --> LIM
    AF --> LIM
    LIM -->|yes| SL[finish step_limit]
    LIM -->|no| RI
    RI -->|turns used up| TL[finish turn_limit]
    NC --> REP
    END --> REP
    SL --> REP
    TL --> REP
    REP[Investigation.report<br/>root_cause_correct = conclusion service<br/>== scenario ground truth<br/>passed = concluded and correct]
    REP --> GR[grading.grade<br/>no conclusion: 0<br/>root_cause 40, cause_evidence 30<br/>via ledger key in scenario.cause,<br/>no_contradicted 20,<br/>efficiency 10 vs reference_steps + 2]
    GR --> OUT[report_lines or report_json<br/>accepted and REJECTED findings<br/>with support status, support counts,<br/>conclusion, refused steps,<br/>score N/100 per criterion]
```

## How it works

1. A **scenario** (`telemetry.py`) is a list of log, metric and deploy records plus a question, the true root cause service, the **cause rows** (marked with `_Cause` when the scenario is built) and the step count of its scripted reference. Three scenarios, each with a trap (D18):
   * `checkout_latency`: a payments deploy cut the db pool; red herrings are a search deploy five minutes earlier and a search cache warning.
   * `config_push`: a gateway config push cut the upstream timeout to 300 ms while api p95 is about 440 ms; red herring is a worker CPU spike to 96% two minutes before the errors.
   * `dependency_outage`: the external `email_vendor` is down; the first deploy (web, page copy) is innocent and the signup deploy comes after the failures began.
2. The **query tools** filter the records. Every row they show is given an evidence id by the **ledger** the first time it is shown (D4, D5). `list_services` and `get_metric` without a metric name only return names, so they issue no ids.
3. The model records **findings** with `report_finding(claim, evidence_ids)` and ends with `conclude(root_cause_service, summary, evidence_ids)`. Both are rejected if they cite nothing or an id the ledger never issued; the error goes back to the model (D7).
4. A finding can carry a **check** (`support.py`): service, field, op, value and an optional `at` time. If its ids are real, the check is compared with the **cited rows only**. One relevant row that holds makes it `supported`; relevant rows that all fail make it `contradicted`; no relevant row makes it `unsupported`; a malformed check is `invalid`. Anything but `supported` rejects the finding, and the error names the rows and their values so the model can fix the claim or cite better rows (D13 to D16). A finding without a check stays `unchecked` and is accepted on its citations alone.
5. The **verdict** is computed by `Investigation.report()` from the ground truth: the run passes only when it concluded with the right service (D8). The model never sees the verdict.
6. The **score** (`grading.py`, D19 to D21) grades the same run out of 100: right service (40), the conclusion cites at least one cause row, found by mapping each cited id to its record key through the ledger (30), no finding was contradicted, even one that was rejected and fixed (20), and steps within the reference plus 2, losing 2 points per extra step (10). A run without a conclusion scores 0. A run can pass and still score 70 when it names the right service but cites no row that shows the cause.
