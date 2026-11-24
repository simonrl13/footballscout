"""Run the open model (system B, later F) on extraction documents, as pre-registered in docs/FINETUNE_PLAN.md §4.

Same input as Claude's extract-v3 request, plus one fixed paragraph that gives SCHEMA as text (Claude got the schema
through structured outputs). Greedy, unconstrained, one document at a time. torch and transformers are imported
lazily, so this module's pure parts load without the finetune group.

  HF_HUB_DISABLE_TELEMETRY=1 uv run --group finetune --env-file .env python -m scout.finetune.infer --smoke
"""
import argparse
import json
import os
import re
import time
from datetime import datetime, timezone

import jsonschema

from scout.data.manifest import ROOT, git_commit
from scout.text import extract_wiki as xw

MODEL = "Qwen/Qwen3-4B-Instruct-2507"
REVISION = "cdbee75f17c01a7cc42f958dc650907174af0554"
MAX_NEW_TOKENS = 2048
RUN_LOG = ROOT / "data" / "finetune" / "runs.jsonl"  # gitignored

SCHEMA_PARAGRAPH = ("Output format: return only one JSON object, with no other text before or after it, that is valid "
                    "against this JSON Schema:\n" + json.dumps(xw.SCHEMA))
SYSTEM = xw.SYSTEM + "\n\n" + SCHEMA_PARAGRAPH  # fixed; never tuned for the open model
_FENCE = re.compile(r"^```[a-zA-Z]*\n(.*)\n```$", re.S)


def user_turn(title: str, text: str) -> str:
    """Exactly the user message of Claude's extract-v3 request."""
    return xw.build_request("x", text, title, "unused")["params"]["messages"][0]["content"]


def messages(title: str, text: str, shots: list[dict] = ()) -> list[dict]:
    """shots: [{"title", "text", "events"}], given as earlier user/assistant turns."""
    out = [{"role": "system", "content": SYSTEM}]
    for s in shots:
        out += [{"role": "user", "content": user_turn(s["title"], s["text"])},
                {"role": "assistant", "content": json.dumps({"events": s["events"]})}]
    return out + [{"role": "user", "content": user_turn(title, text)}]


def parse(raw: str, hit_limit: bool) -> dict | None:
    """The pre-registered parse: strip whitespace and at most one enclosing code fence, json.loads, SCHEMA check.
    None = failed extraction (no retry, no repair)."""
    if hit_limit:
        return None
    s = raw.strip()
    m = _FENCE.match(s)
    s = m.group(1).strip() if m else s
    try:
        out = json.loads(s)
        jsonschema.validate(out, xw.SCHEMA)
    except (json.JSONDecodeError, jsonschema.ValidationError):
        return None
    return out


def load():
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
                           bnb_4bit_use_double_quant=False)
    kw = {"revision": REVISION, "trust_remote_code": False}
    tok = AutoTokenizer.from_pretrained(MODEL, **kw)
    model = AutoModelForCausalLM.from_pretrained(MODEL, quantization_config=q, device_map={"": 0}, use_safetensors=True, **kw)
    return tok, model.eval()


def generate(tok, model, msgs: list[dict]) -> dict:
    import torch
    torch.cuda.reset_peak_memory_stats()
    t0 = time.perf_counter()
    ids = tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt", return_dict=True).to(model.device)
    with torch.no_grad():
        out = model.generate(**ids, do_sample=False, max_new_tokens=MAX_NEW_TOKENS)
    new = out[0, ids["input_ids"].shape[1]:]
    seconds = time.perf_counter() - t0
    return {"raw": tok.decode(new, skip_special_tokens=True), "seconds": round(seconds, 2),
            "prompt_tokens": int(ids["input_ids"].shape[1]), "output_tokens": int(len(new)),
            "hit_limit": len(new) >= MAX_NEW_TOKENS,
            "peak_vram_gib": round(torch.cuda.max_memory_allocated() / 2**30, 3),
            "peak_reserved_gib": round(torch.cuda.max_memory_reserved() / 2**30, 3)}


def environment() -> dict:
    import bitsandbytes, torch, transformers
    free, total = torch.cuda.mem_get_info()
    return {"commit": git_commit(), "model": MODEL, "revision": REVISION, "torch": torch.__version__,
            "transformers": transformers.__version__, "bitsandbytes": bitsandbytes.__version__,
            "BNB_CUDA_VERSION": os.environ.get("BNB_CUDA_VERSION"), "gpu": torch.cuda.get_device_name(0),
            "free_vram_at_start_gib": round(free / 2**30, 3), "total_vram_gib": round(total / 2**30, 3)}


def log_run(record: dict) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RUN_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def smoke_docs(conn) -> tuple[dict, list[dict]]:
    """Memory smoke test inputs, none from the sampled sets: the target is the unsampled document whose stored
    extract-v3 input size is closest to the longest test document's; the 3 stand-in shots are unsampled documents
    closest to the dev median. Stand-in shots carry empty event lists: no labels exist and Claude outputs can't be
    examples. Token targets are Claude's stored counts for the sampled documents (metadata only, no text read)."""
    import pandas as pd
    from scout.finetune.sample import SAMPLE_FILE, load_docs
    sampled = pd.read_csv(SAMPLE_FILE)
    tok = dict(conn.execute("SELECT doc_id, input_tokens FROM text_extractions WHERE prompt_version = 'extract-v3' "
                            "AND input_tokens IS NOT NULL").fetchall())
    s = sampled.assign(tok=sampled.doc_id.map(tok))
    target_len, shot_len = s[s.split == "test"].tok.max(), s[s.split == "dev"].tok.median()
    pool = load_docs(conn)
    pool = pool[~pool.doc_id.isin(sampled.doc_id) & ~pool.player_id.isin(sampled.player_id)].assign(tok=lambda d: d.doc_id.map(tok))
    titles = dict(conn.execute("SELECT doc_id, meta->>'title' FROM text_documents WHERE doc_id = ANY(%s)", (pool.doc_id.tolist(),)).fetchall())
    pick = lambda d: {"doc_id": d.doc_id, "title": titles[d.doc_id], "text": d.text, "claude_input_tokens": int(d.tok)}
    order = (pool.tok - target_len).abs().sort_values().index
    target = pick(pool.loc[order[0]])
    rest = pool.drop(order[0])
    shots = [pick(r) | {"events": []} for r in rest.loc[(rest.tok - shot_len).abs().sort_values().index[:3]].itertuples()]
    return target | {"target_claude_tokens": int(target_len), "shot_claude_tokens": float(shot_len)}, shots


def main() -> None:
    from scout.text import store
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", required=True, help="memory smoke test (not scored)")
    ap.parse_args()
    with store.connect() as conn:
        target, shots = smoke_docs(conn)
    env = environment()
    tok, model = load()
    rec = {"kind": "smoke", "at": datetime.now(timezone.utc).isoformat(), **env, "setup": "3-shot (stand-in shots)",
           "doc_id": target["doc_id"], "shot_doc_ids": [s["doc_id"] for s in shots]}
    try:
        r = generate(tok, model, messages(target["title"], target["text"], shots))
        rec |= {"completed": True, **{k: v for k, v in r.items() if k != "raw"}}  # output not kept: not scored
    except Exception as e:  # torch.OutOfMemoryError included: reported, never retried here
        rec |= {"completed": False, "error": f"{type(e).__name__}: {e}"[:500]}
    log_run(rec)
    print(json.dumps({k: rec[k] for k in rec if k not in ("shot_doc_ids",)}, indent=1, default=str))


if __name__ == "__main__":
    main()
