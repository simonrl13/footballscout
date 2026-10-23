"""One-off validation of the direction check (fix 2, 2026-10-23) on recorded answers: no live model calls, no tuning.

Every case is replayed through the agent loop with model responses taken only from the response cache (agent_cache);
the client raises instead of calling the API, so an unrecorded request makes the case "not replayable". The direction
check is evaluated on every answer the model gives but not enforced, so the replay follows the recorded path exactly;
the report says which released answers it would have flagged (each would have been retried, and blocked if the retry
failed too).

--code-root replays with another checkout's agent code (the held-out answers were recorded at commit be92cd3, before
a system-prompt change, so only that code reproduces their requests); the check always comes from this file's repo.

Usage: uv run --env-file .env python scout/evals/direction_replay.py --set dev
       uv run --env-file .env python scout/evals/direction_replay.py --set heldout --code-root <be92cd3 checkout>
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--set", choices=["dev", "heldout"], required=True)
ap.add_argument("--code-root", help="checkout whose agent code replays the answers (default: this repo)")
args = ap.parse_args()
if args.code_root:
    sys.path.insert(0, str(Path(args.code_root).resolve()))

from scout.agent import agent, tools  # noqa: E402  (after the code-root switch)
from scout.evals import run as evals  # noqa: E402

spec = importlib.util.spec_from_file_location("direction_numbers", HERE.parent / "agent" / "numbers.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)  # this repo's contradictions(), whatever --code-root is


class NotRecorded(Exception):
    pass


class NoLiveClient:
    class messages:
        @staticmethod
        def create(**_):
            raise NotRecorded


class ReplayTracer(agent.Tracer):
    """Reads the response cache; writes nothing (no trace rows, no violations, no cache entries)."""

    def __init__(self):
        super().__init__()
        self.responses, self.new, self.violations = {}, {}, []

    def call(self, *a, **k):
        pass

    def violation(self, conversation_id, kind, detail, action):
        self.violations.append({"kind": kind, "numbers": detail["numbers"], "action": action})

    def cache_put(self, key, response):
        raise NotRecorded


def main() -> None:
    import os
    model = os.environ["AGENT_MODEL"]
    cases = [json.loads(x) for x in Path(evals.SETS[args.set]).read_text(encoding="utf-8").splitlines() if x.strip()]
    seen = []  # (answer, flagged) for every answer the model gave in the current case

    def observing_unsupported(answer, sources, real=agent.unsupported):
        seen.append((answer, check.contradictions(answer, sources)))
        return real(answer, sources)  # enforcement unchanged: the recorded path is followed
    agent.unsupported = observing_unsupported
    if hasattr(agent, "contradictions"):
        agent.contradictions = lambda answer, sources: []  # observe only, even on code that already has the check

    rows, tracer = [], ReplayTracer()
    with tools.connect() as db:
        for case in cases:
            seen.clear()
            try:
                res = evals.run_case(case, NoLiveClient(), tracer, db, model)
            except NotRecorded:
                rows.append({"case": case["id"], "replayed": False})
                continue
            final = res["events"][-1]
            released = final["type"] == "answer"
            flagged = [f for _, f in seen if f]
            last_flag = seen[-1][1] if seen else []
            rows.append({"case": case["id"], "replayed": True, "outcome": final["type"], "answers_checked": len(seen),
                         "released_flagged": released and bool(last_flag), "flags": last_flag if released else [],
                         "any_flag": bool(flagged)})
    replayed = [r for r in rows if r["replayed"]]
    print(json.dumps({"set": args.set, "agent_code": agent.__file__, "check_code": spec.origin,
                      "cases": len(rows), "replayed": len(replayed),
                      "not_replayable": [r["case"] for r in rows if not r["replayed"]],
                      "released": sum(r["outcome"] == "answer" for r in replayed),
                      "answers_checked": sum(r["answers_checked"] for r in replayed),
                      "released_now_flagged": [r for r in replayed if r["released_flagged"]],
                      "any_answer_flagged": [r["case"] for r in replayed if r["any_flag"]]}, indent=1))


if __name__ == "__main__":
    main()
