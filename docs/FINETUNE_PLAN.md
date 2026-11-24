# Fine-tuning experiment: a small open model for Wikipedia event extraction

Plan written 2026-11-24 (stage 0) and approved the same day with these decisions:
- **Staged.** The test set (150) and dev set (30) are labelled first. Claude (C) and the base model (B) are compared on
  them. Whether to label the train set and train at all is decided only after the owner sees that result.
- **Sizes:** 150 / 150 / 30 (test / train / dev).
- **Terms:** hand labels only. No authorization request to Anthropic.
- **Claude latency:** the ~US$0.04 of live calls on the 150 test documents is approved.
- **Goal:** local extraction with no API dependency. It is not cost savings.

Nothing has been installed or downloaded yet, and each new dependency still needs the owner's approval.

**Question.** Can a small open model (1–4B parameters) run Scout's Wikipedia event extraction (`extract-v3`) locally,
with no API dependency, at quality close to Claude's, as measured against hand labels? The model is tried first as
is (B), and fine-tuned with QLoRA (F) only if the owner decides so after B. "Claude stays" is an acceptable answer.

**What the result can and can't change.** Two facts from the audit (§1) frame the experiment:
- **It can't save meaningful money.** The full corpus is already extracted, for US$2.77.
- **It can't change a shipped metric.** The features built from the extraction were a pre-registered negative result
  (B0 stays the baseline, 2026-10-12), and nothing in the demo uses them.

So the goal is **local extraction with no API dependency**. The experiment measures quality, reliability and
latency, and reports cost only for completeness. If the small model is close enough to Claude, that shows an
extraction step like this can run on local hardware. That is the claim on offer, and it is the only one.

## 1. Data audit (local Postgres, 2026-11-24)

**The unit is a document, not a passage.** The premise "37,375 passages" mixes up two tables:
- **Extraction documents.** A document is the text added to a player's Wikipedia page during the year before a
  snapshot: the sentences in the revision in force at t that weren't in the revision a year earlier. There is one
  document per labelled snapshot player-year (`scout/text/wiki_run.py`), with doc_id
  `wikipedia:enwiki:diff:<old>:<new>`.
- **Passages.** `text_passages` holds 37,375 chunks of the current revisions of 2,616 demo players, built for
  `search_text` retrieval. They were never meant to be extracted and have no labels.

**What exists:**

| Prompt version | Model | Documents | Status | Input / output tokens | Raw output stored |
|---|---|---|---|---|---|
| `extract-v2` (pilot 1) | claude-haiku-4-5 | 100 | succeeded | 141,695 / 17,079 | 100 |
| `extract-v2` (pilot 2) | claude-haiku-5-5 | 100 | succeeded | 146,628 / 15,237 | 100 |
| **`extract-v3`** (full run) | claude-haiku-5-5, Batch API, effort low | **24,260** | all succeeded | 36,896,915 / 3,683,221 | 24,260 |

- **Format:** JSON per the `SCHEMA` in `scout/text/extract_wiki.py`. Each document returns a list of events, and each
  event has six fields: `type`, `date`, `injury_type`, `duration_days`, `contract_until` and `evidence`.
- **Storage:** the raw outputs are in `text_extractions.output`. Verified signals are in `text_signals`, stored as
  offsets into the document (the quote is the text between them).
- **Nothing is left to extract.** Every eligible document has a `extract-v3` output. The only unextracted text is the
  passages, which aren't extraction units.

**Verification of the full run.** Claude returned 34,801 events, and 9,755 (28%) passed every check
(`reports/m3a_extraction.md`). Drops by reason:

| Reason | Events |
|---|---|
| Date outside the 12-month window | 18,259 |
| Year-only date | 5,589 |
| Year not supported by the text (`context-year` rule) | 525 |
| Unparseable date | 522 |
| **Quote not verbatim** | **151** |

**Quote pass rate: 99.6%** (34,650 of 34,801 events have a verbatim quote). Almost all drops are date and window
rules, not hallucinated quotes. Separately, 4,230 contract end dates (`contract_until`) passed for 2,182 players.

**Label distribution:**

| Type | Raw events | Kept | Documents with a kept event |
|---|---|---|---|
| transfer | 15,243 | 3,856 | 3,749 |
| loan | 7,426 | 2,061 | 1,871 |
| contract_extension | 6,903 | 2,399 | 2,372 |
| injury | 4,059 | 1,025 | 942 |
| contract_expiry | 1,170 | 414 | 410 |
| contract_until (attribute) | n/a | 4,230 | 3,603 |

**Document shape:**
- **Events:** 7,636 documents (31%) return no event. Of the rest, 7,903 return 1, 4,177 return 2, and 2,162 return 3;
  the maximum is above 10.
- **Length:** input tokens including the ~430-token system prompt are 1,055 / 1,251 / 2,215 / 4,866 at p10 / p50 /
  p90 / p99. The maximum is 30,662.
- **Spread:** snapshot years 2013–2024 are roughly even, at 1,862–2,187 documents per year.

**Existing quality evidence.** There are no human labels for extraction quality. The only check is the comparison of
moves with the Transfermarkt transfers table: precision 94% (95% CI 93–94%) and recall 55%, scored only on players
the table covers. There is no ground truth for contracts or injuries.

## 2. Terms check

### Anthropic

Read on 2026-11-24. The pages show Commercial Terms "Effective Jun 17, 2025" and Usage Policy "Effective Nov 12,
2026". The quotes are exact fragments.

- **Commercial Terms §B:** "Subject to Customer's compliance with these Terms, Anthropic hereby assigns to Customer its
  right, title and interest (if any) in and to Outputs."
- **Commercial Terms §D.2:** "Customer and its Users may only use the Services in compliance with these Terms,
  including (a) the Usage Policy".
- **Commercial Terms §D.4:** "Customer may not and must not attempt to (a) access the Services to build a competing
  product or service, including to train competing AI models or resell the Services except as expressly approved by
  Anthropic;".
- **Usage Policy, "Do Not Abuse Our Platform":** "Use outputs to train an AI model (e.g., "model scraping" or "model
  distillation")" … "without prior authorization from Anthropic".

**Reading.** The Usage Policy bullet has no "competing" qualifier, and §D.2 makes the Usage Policy binding. So
**fine-tuning on the stored Claude outputs isn't clearly allowed**: as written, it needs Anthropic's prior
authorization, whether or not an extraction model counts as "competing". This is a reading of the text, not legal
advice.

**Plan under this reading (the fallback):**
- **Claude is used only for the evaluation comparison.** Its stored `extract-v3` outputs on the test documents are
  scored against the hand labels. That uses Claude outputs to evaluate a model, not to train one.
- **Training data is hand-labelled by the owner** (§3). Few-shot examples for the base model also come from the hand
  labels, not from Claude outputs.
- **Optional (owner's call):** ask Anthropic for written authorization to fine-tune on the 24,260 stored outputs. If
  it is granted, a fourth arm (trained on Claude labels) could be pre-registered separately. That arm is not in this
  plan.

### Wikipedia, CC BY-SA 4.0

Read from the legal code and Wikipedia's "Reusing Wikipedia content" page.

- **Local use** (training and evaluating on this machine): nothing is "Shared" in the licence's sense, so no
  condition is triggered.
- **Publishing the dataset** (excerpts with labels): sharing the excerpts requires the licence's attribution
  conditions (§3(a)): a link to each exact revision or diff, a note that the text was modified, and the licence
  notice. If the labelled dataset counts as Adapted Material ("derived from or based upon the Licensed Material"),
  ShareAlike (§3(b)) applies: it must be published under BY-SA 4.0 or a compatible licence, with no added
  restrictions. Every document here already has its diff URL.
- **Publishing the weights:** the legal code doesn't say whether trained weights are Adapted Material, and the
  Wikipedia page doesn't mention training or models. The base model's licence (Apache-2.0 for the recommendation)
  also applies.

  If weights are ever published, the safe course is attribution plus a BY-SA-compatible licence. That combination
  needs the owner's decision and probably legal advice. **Default: nothing is published.**
- **Labels are the owner's work.** The Claude outputs aren't in any published artifact.

## 3. Hand-labelled data: test set first

**Units and split:**
- **Units:** the `extract-v3` documents, exactly as Claude saw them (same text, player name and window).
- **Split by player.** `player_id` is hashed with a fixed seed into test 50%, train 40% and dev 10%. All of a
  player's documents land in one split, so a page never appears in both training and test.
- **Locking the test set:** test documents are drawn and their IDs committed before any labelling. Their labels are
  never used for training, prompt writing or picking the training stopping point.

**Sampling, independent of every system.** Sampling on Claude's output would favour documents Claude handles. So the
strata come from a keyword pre-filter on the document text, written into the code before sampling:
- **injury:** injur, ruptur, ligament, surgery, sidelined, ruled out, fracture, strain;
- **contract:** contract, extension, extended, until 20, free transfer, released, terminated;
- **loan:** "loan";
- **transfer:** joined, signed for, moved to, transfer, fee;
- **none:** matches no keyword.

A document goes to the first stratum it matches, in the order injury, contract, loan, transfer, none, so the rarest
type is filled first.

| Set | Documents | Allocation | Purpose |
|---|---|---|---|
| **Test** | **150** | 30 each from injury, contract, loan, transfer, none | Ground truth for every comparison |
| Dev | 30 | 6 per stratum | B's few-shot examples and variant choice; F's epoch; never used for the decision |
| Train | 150 | 30 per stratum | QLoRA training; labelled only if the owner decides to train after B |

**Drawn 2026-11-24** with `python -m scout.finetune.sample`. The sets are in `docs/evals/finetune_sample.csv`
(document and player IDs only, no text). There were 24,093 candidates: the 24,260 `extract-v3` documents minus the
167 that a pilot had already extracted. The script refuses to redraw once the file exists.

**Sizes and effort:**
- **Size estimate:** 150 test documents should hold about 70–120 kept gold events. Main-type F1 intervals will be
  about ±9 points; injury and contract_expiry will be thin.
- **Labelling time,** measured on the drawn sets, is **about 12 h for test and dev**, plus **about 10 h for train only
  if training goes ahead**. The basis: the test documents total about 36,000 words (median 120 words, longest
  about 2,000), and the dev documents about 15,000 (median 270). The §1 token counts are larger because they include
  the system prompt and the output schema. At about 4 minutes per document, that is
  roughly 10 h for test and 2 h for dev.

**Labelling guide** (`docs/evals/finetune_labelling.md`, written in stage 1). It follows the extraction prompt's own
rules, so the gold set and the systems answer the same question:

1. **What counts as an event:**
   - **injury:** an injury he suffered;
   - **contract_extension:** a new or extended contract with his current club;
   - **contract_expiry:** his contract ran out, he left on a free, or it was terminated;
   - **loan:** he joined or returned from a loan;
   - **transfer:** a permanent move to another club.

   Rumours, interest, bids and speculation don't count.
2. **Use only the text in front of you.** If you know something happened but the text doesn't say it, don't label it.
3. **date:** as the text gives it, written YYYY-MM-DD, YYYY-MM or YYYY. Don't infer a missing part. The year can come
   from the sentence, or from the paragraph or season heading where the text clearly carries it (the `context-year`
   rule).
4. **contract_until:** the end date only when the text states it. **injury_type** and **duration_days:** only when
   stated.
5. **evidence:** the shortest exact fragment that states the event, at most 300 characters, copied character for
   character. The labelling script checks it with `locate()` and rejects anything that isn't verbatim.
6. **One row per event.** A document with no events gets one row with type `none`, so "no events" is a recorded
   label, not a missing one.
7. **Hard cases go in a `note` column** rather than being forced into a label: a date that is ambiguous, two events
   in one sentence, or a loan converted to a transfer.

**Format and checking:**
- **Format:** a CSV per set under `labeling/finetune/` (gitignored). Columns: `doc_id`, `row`, `type`, `date`,
  `contract_until`, `injury_type`, `duration_days`, `evidence`, `note`. The script renders each document with numbered
  lines next to an empty sheet.
- **Second-pass check:** I re-read a random 10% of the owner's test labels and flag disagreements. Agreement is
  reported, but labels are never changed without the owner's decision.

## 4. Pre-registered evaluation

This section is fixed before any labels exist. It was copied into `docs/RESEARCH_LOG.md` as a PRE-REGISTRATION
entry (2026-11-24) and committed before any labelling, scoring or model download.

**Systems,** all given the same input (system prompt, `Player: …`, `<text>…</text>`):
- **C (Claude):** the stored `extract-v3` outputs. No new calls are needed to score quality.
- **B (base model):** the small model with no fine-tuning, in two variants:
  - zero-shot with the `extract-v3` prompt;
  - 3-shot, with 3 dev documents and their hand labels as examples. The 3 documents are drawn with seed 20261124 from
    the dev documents that have at least one labelled event.

  The variant with the higher kept-event F1 on the other 27 dev documents is the one scored on test. Ties go to
  zero-shot. Decoding is greedy, without constrained decoding. JSON validity is a measured outcome, so the model gets
  no help with it. (The plan first took the shots from the train split. That split isn't labelled in the staged
  plan.)
- **F (fine-tuned), only if the owner decides to train after seeing B:** QLoRA on the train split, with the same
  prompt and greedy decoding.
- **Prompt for B and F:** the `extract-v3` system prompt, followed by a fixed paragraph that gives the JSON `SCHEMA`
  as text. Claude received the schema through structured outputs, so without the paragraph the open model wouldn't
  see the format at all.

Every system's output goes through the unchanged `verify_events` and `contract_statements` functions.

**Inference settings for B (and F), fixed before any run (amendment 2026-11-24):**
- **Weights:** `Qwen/Qwen3-4B-Instruct-2507` at revision `cdbee75f17c01a7cc42f958dc650907174af0554`, loaded with
  `use_safetensors=True` and `trust_remote_code=False`. The repository has three safetensors shards, 8.04 GB in all,
  and is Apache-2.0, not gated.
- **Precision:** 4-bit NF4 via bitsandbytes, with bf16 compute and no double quantization. This runs on the owner's
  RTX 3050: desktop, 6 GB VRAM, 70 W, driver 616.92 with CUDA 13.4.
- **Decoding:** unconstrained. transformers 5.22.2 has no JSON-schema-constrained decoding without a new dependency
  such as outlines or xgrammar. Its `generate` has no grammar option, and `response_format` appears in the serving
  code only in a list of parameter names, not in any decoding logic.

  Generation is greedy (`do_sample=False`), one document at a time, with `max_new_tokens=2048` and the model's own
  chat template (system prompt, then the user turn in `extract-v3`'s format).
- **Parsing:** strip surrounding whitespace and at most one enclosing Markdown code fence, then `json.loads`. Then
  check the result against `SCHEMA`: required keys present, field types right, `type` in the enum.
- **A failed extraction** is output that doesn't parse, fails the `SCHEMA` check, or stops at `max_new_tokens`. It
  counts as zero events for that document: every gold event in it is a false negative, and the document counts
  toward the invalid-JSON rate. There is no retry and no repair.

  The same applies to C: a stored `extract-v3` result with status `refusal` or `max_tokens` is a failed extraction.
- **Latency:** wall-clock time per document, from tokenization through `generate`. One warm-up document is run first
  and excluded.
- **Out of memory and other deviations:** an out-of-memory error stops the run, and it is reported. Any change to
  precision, length limits or hardware is logged in the research log as a deviation before the re-run. Moving to
  Kaggle counts as a hardware change. None of these are switched silently.
- **No prompt tuning for Qwen.** B and F get exactly the `extract-v3` system prompt plus the fixed schema paragraph.

**Matching.** A system event matches a gold event when:
- the `type` is the same;
- the `date` agrees at the gold precision;
- the evidence spans overlap, or fall in the same sentence line.

Matching is one-to-one and greedy, in document order.

**Metrics,** all on the 150 test documents:

| Metric | Definition | Level |
|---|---|---|
| **Primary: kept-event micro-F1** | F1 over events that pass verification, gold filtered by the same window and date rules | Pipeline output (what features use) |
| F1 per type | Same, by type; contract_expiry reported only | Per type |
| Raw-event F1 | All events stated in the text, before the window and date filters | Extraction ability |
| Field accuracy on matched events | `contract_until` (exact at gold precision), `injury_type` (normalised exact), `duration_days` (exact) | Per field |
| Quote pass rate | Share of returned events whose evidence is verbatim | Per event |
| Invalid-JSON rate | Share of documents whose output doesn't parse or fails the schema; counted as zero events, no retry | Per document |
| Cost per 1,000 documents | C: the measured Batch API cost (US$0.114). B/F: GPU hours at the stated hourly rate, or US$0 locally (electricity not costed) | Per system |
| Latency p50 / p95 | Seconds per document | Per system |

- **Intervals:** 95% intervals come from a paired bootstrap over documents (10,000 resamples, seed 20261124).
- **Claude's latency:** the stored outputs came from the Batch API, so they have no per-request latency. Live
  latency comes from 150 non-batch calls on the test documents (about US$0.03–0.04; owner approved up to US$0.06 on
  2026-11-24). They run serially, with the same model, effort and request as `extract-v3`. Only their latency is
  used, not their outputs, so C's quality is still the stored run's.

**Decision rule.** F replaces C as the recommended extractor only if all five conditions hold:
1. **F1 close to Claude's:** F's kept-event micro-F1 is at least C's minus 3 points, and the lower bound of the paired
   95% interval for F − C is at least −6 points.
2. **Quote pass rate:** at least 98% for F (Claude's measured full-run rate is 99.6%).
3. **Invalid JSON:** at most 1% of documents for F.
4. **No type falls behind badly:** for every type with at least 25 gold kept events, F's F1 is at least C's minus 10
   points.
5. **Fast enough:** p95 latency for F is at most 10 s per document on the hardware used. (The extraction is a batch
   job, so speed is a sanity bound, not a goal.)

Otherwise **Claude stays**.

**How condition 1 is judged at n = 150.** The test set is resampled by document, 10,000 times with seed 20261124.
Each resample recomputes both systems' micro-F1 from pooled counts on the same documents, and the 2.5th and 97.5th
percentiles of the difference form the paired 95% interval. Condition 1 needs two things:
- the point estimate of the difference is at least −3 points;
- the interval's lower bound is at least −6 points.

If the interval is too wide to clear −6, condition 1 fails. That is reported as "closeness not shown", not as "the
model is worse".

**Staged use of the rule:**
- **Stage 3:** B is scored on test and checked against the same five conditions, with B in place of F.
- **If B passes all five,** training stops there. The finding is that the base model is enough, and the train set
  isn't labelled.
- **If B fails and its kept-event F1 is no more than 30 points below C's,** training is recommended. The owner labels
  the train set and runs F, which is then scored on the same test set. Failures of the JSON, quote or latency
  conditions alone also recommend training, since fine-tuning targets output format directly.
- **If B's kept-event F1 is more than 30 points below C's,** training is not recommended. 150 examples are unlikely
  to close a gap that size, so the experiment stops and reports B.

The 30-point line is a judgement fixed in advance, not a derived threshold. The owner can always decline the train
labelling for time, and that is recorded as the reason F doesn't exist.

Seeing B's test result before deciding to train is a known look at the test set. It can change only whether F
exists, not how F is built: F's hyperparameters, prompt and epoch rule are fixed above. It is reported with the
result.

**Fixed in advance:**
- **One training run counts.** The hyperparameters in §6 are fixed. Dev may pick the epoch checkpoint (1, 2 or 3), and
  nothing else. A crashed run is repeated once and reported, as in the text-experiment protocol.
- **The test set is scored once per system.**
- **Every run is recorded in the research log, failed ones included.**

**Known threats, reported with the result:**
- **The model may already know the events.** Wikipedia is in the base models' pretraining data. The verbatim-quote
  and year rules limit what that can do.
- **Claude's prompt was tuned on pilot documents.** Those 200 pilot documents are excluded from the test sample.
- **`extract-v3` was developed on Claude** (two pilots, then the full run). The prompt was never tuned for Qwen, and
  won't be, so B is measured with a prompt written for another model. This may understate what a small model could
  do with its own prompt. It is a known limitation, reported with the result.
- **One labeller.** The 10% second pass is the only check on the owner's labels.

## 5. Model shortlist

Checked on the Hugging Face API on 2026-11-24. Only configuration and metadata files were read; no weights were
downloaded.

| Model | Size | Licence (commercial use) | Context | Access | Structured output |
|---|---|---|---|---|---|
| **Qwen/Qwen3-4B-Instruct-2507** (recommended) | 4.0B | Apache-2.0: yes | 262,144 | Open, not gated; ~11.4M downloads | Instruct, non-thinking variant; trained for tool calls and JSON. Text-only `Qwen3ForCausalLM`, supported by transformers, peft and trl |
| microsoft/Phi-4-mini-instruct | 3.8B | MIT: yes | 131,072 | Open | Function-calling format in the model card. Dense decoder |
| ibm-granite/granite-4.2-3b | ~3B | Apache-2.0: yes | 131,072 | Open; released 2026-08-07 | Instruct, tool-calling. `GraniteForCausalLM` |

**Recommendation: Qwen3-4B-Instruct-2507.**
- It has the cleanest licence and the longest context.
- It is text-only.
- It has no thinking mode to switch off, so it adds no hidden tokens to latency.
- It is the most-used model in the range, so peft and trl support is mature.

Phi-4-mini is the fallback if Qwen's JSON validity is poor on dev.

**Considered and excluded:**

| Model | Why it's excluded |
|---|---|
| Qwen3.5-4B / 2B (Apache-2.0, Feb 2026) | Vision-language architecture (`Qwen3_5ForConditionalGeneration` with a vision tower). It adds memory and risk for a text-only task |
| Llama 3.2 3B | Custom licence with its own acceptable-use policy and attribution terms; gated |
| Gemma 3 4B | Gemma terms with a prohibited-use policy; gated |
| Qwen2.5-3B | Licence "other" (the Qwen research licence) |
| Qwen3-1.7B | Kept as a possible size ablation, not pre-registered |

The weights are pinned to the commit SHA at download: `cdbee75f17c0…` for Qwen3-4B-Instruct-2507 as of today.

## 6. Compute plan

- **Local first:** this machine has an RTX 3050 with 6 GB. QLoRA (4-bit NF4) of a 4B model uses about 2.5 GB for
  weights. LoRA r = 16 with gradient checkpointing and batch size 1 should fit at a sequence cap of about 3,072
  tokens, which covers about 95% of documents. Longer documents in the train split are skipped. Longer test documents
  are processed whole at inference.

  Local means no data leaves the machine and costs US$0. This needs confirming with a 10-step smoke run first.
- **Fallback: Kaggle Notebooks, free** (T4 16 GB, about 30 GPU-hours a week). Training would mean uploading a private
  Kaggle dataset: the train and dev documents (public CC BY-SA text) and the owner's labels. No secrets and no Claude
  outputs go into it. This needs a Kaggle account, which is an external service, so the owner decides. The second
  fallback is a rented GPU: an L4 or A10 at roughly US$0.5–1 an hour on the main GPU clouds, an estimate I haven't
  checked against today's prices. Two hours would be about US$2. Nothing is spent without the owner's OK.
- **Fixed settings:** 3 epochs, LoRA r = 16, alpha = 32, dropout 0.05, all linear layers, learning rate 2e-4 with
  cosine decay and 3% warmup, effective batch size 8, seed 20261124.

**Time estimates** (rough; refined after the smoke run):

| Step | RTX 3050 (local) | T4 (Kaggle) |
|---|---|---|
| B inference, two variants on 30 dev documents, then the chosen one on 150 test (4-bit) | about 1 h | 20–30 min |
| Only if training goes ahead: 150 documents × ~1.3k tokens × 3 epochs ≈ 0.6M tokens | about 1 h | 20–30 min |
| Only if training goes ahead: F inference on 30 dev × 3 checkpoints + 150 test | about 1 h | 20–30 min |
| Total GPU time | about 1 h for B; about 3 h with F | about 1–1.5 h |

## 7. Dependency vetting

Checked on PyPI and OSV on 2026-11-24. For each package, the pin is the newest stable release at least 14 days old
(uploaded on or before 2026-11-10). OSV lists no advisories for any pinned version.

| Package | Pin | Released | Newest (too new) | Licence | Maintainer / source |
|---|---|---|---|---|---|
| torch | 2.15.0 | 2026-10-28 | — | BSD-3 family (PyPI expression lists several) | PyTorch Team, pytorch.org |
| transformers | 5.22.2 | 2026-11-06 | 5.24.0 (2026-11-21) | Apache-2.0 | Hugging Face, github.com/huggingface/transformers |
| peft | 0.21.2 | 2026-10-01 | 0.22.0 (2026-11-19) | Apache-2.0 | Hugging Face |
| trl | 1.17.1 | 2026-10-30 | 1.18.2 (2026-11-19) | Apache-2.0 | Hugging Face (L. von Werra) |
| accelerate | 1.15.0 | 2026-09-09 | 1.16.0 (2026-11-16) | Apache-2.0 | Hugging Face |
| bitsandbytes | 0.50.2 | 2026-08-27 | — | MIT | T. Dettmers / bitsandbytes-foundation |
| datasets | 5.2.0 | 2026-11-09 | — | Apache-2.0 | Hugging Face. Optional: trl accepts plain lists, so it may be dropped |
| safetensors | 0.8.0 | 2026-06-09 | — | Apache-2.0 | Hugging Face. Transitive |
| tokenizers | 0.23.3 | 2026-10-09 | — | Apache-2.0 | Hugging Face. Transitive |
| huggingface-hub | 2.4.0 | 2026-10-29 | — | Apache-2.0 | Hugging Face. Transitive; downloads the weights |

**Installed for stage 3 (owner-approved 2026-11-24):**
- **Direct pins:** torch `2.15.0+cu134`, transformers 5.22.2, accelerate 1.15.0, bitsandbytes 0.50.2, safetensors
  0.8.0, tokenizers 0.23.3, huggingface-hub 2.4.0.
- **13 new transitive packages:** fsspec 2026.9.0, hf-xet 1.8.0, markdown-it-py 4.3.0, mdurl 0.1.2, mpmath 1.3.0,
  networkx 3.7, regex 2026.11.9, rich 15.0.0, setuptools 84.2.1, shellingham 1.5.4, sympy 1.14.0, tqdm 4.70.1 and
  typer 0.29.0. All are released on or before 2026-11-10, with no OSV advisories. No existing package changed.
- **Not yet:** peft, trl and datasets are needed only if training goes ahead, and are approved separately then.

**How the group is set up:**
- **Always `uv run --group finetune …`.** Every experiment command uses it, the labelling scripts included. A plain
  `uv sync` syncs the default groups only and removes the experiment's packages.
- **Isolation:** the `finetune` group is kept out of `default-groups`. So `uv sync`, the CI `tests` job and the API
  image never install it.
- **Windows only:** torch, accelerate and bitsandbytes carry `sys_platform == 'win32'`. With the marker on torch alone,
  accelerate and bitsandbytes had pulled in PyPI's torch for other platforms, along with 15 nvidia-* packages and
  triton. The lock now has none of them.
- **Second index:** torch's CUDA build comes from `https://download.pytorch.org/whl/cu134`, declared with
  `explicit = true` and mapped to torch alone in `[tool.uv.sources]`. Nothing else resolves from it, and the lock
  has one torch: `2.15.0+cu134`, Windows wheel only. PyPI's Windows torch wheel is CPU-only.
- **Temporary caps:** transformers would have pulled regex 2026.11.23 and typer 0.29.2, both under 14 days old. They
  are capped in `constraint-dependencies` at regex 2026.11.9 and typer 0.29.0. The caps come off after 2026-12-02
  (typer) and 2026-12-07 (regex).
- **Audit scope:** CI's audit runs on Linux, where pip-audit skips every `win32`-only package. A separate CI step
  audits those packages at their base versions, since the `+cu134` build isn't on PyPI. The step fails if torch,
  accelerate or bitsandbytes is missing from that list. Auditing base torch 2.15.0 assumes the CUDA build has the
  same advisories.
- **Not proposed:** no constrained-decoding library (outlines, xgrammar), because JSON validity is one of the things
  measured. vLLM is out too: plain `generate` is enough at this scale.
- **Version drift:** pins are rechecked on the day of install. A newer release that becomes allowed by then may
  replace one of these, and the owner sees it either way.

## 8. Security and repo hygiene

**SECURITY.md** (updated in the same PR as the code):
- **New dependencies:** the `finetune` group, its pins, why it's kept out of the API image, and that pip-audit covers
  it in the `--all-groups` audit.
- **Model provenance:** the Hugging Face repository, the pinned commit SHA and the licence (Apache-2.0). Weights load
  as safetensors only, with `trust_remote_code=False`. Downloads go through `huggingface_hub` with no token (the model
  isn't gated).
- **What leaves the machine:**
  - nothing beyond the model download if training runs locally;
  - with Kaggle, the train and dev documents (public Wikipedia text) and the owner's labels go to a private Kaggle
    dataset;
  - no Claude outputs, no secrets and no database dump.
- **Notebooks:** if Kaggle is used, `nbstripout` isn't added. The notebook is a thin wrapper that calls
  `scout.finetune`, has no keys in it (Kaggle needs none for a public model), and gitleaks scans it in pre-commit and
  CI.
- **AI-features section:** document text is untrusted input to the small model, as it is to Claude. Outputs are data,
  and the same verifier drops anything without a verbatim quote.

**RESEARCH_LOG.md:**
- the pre-registration (§4 plus the sampling rule in §3), committed before any training or test-set scoring;
- one entry per run, failed runs included.

**Code:**
- `scout/finetune/` holds typed Python with tests and no network calls in tests:
  - `sample.py`: split and strata;
  - `labels.py`: render documents, validate the CSV with `locate()`;
  - `score.py`: matching, F1 and bootstrap;
  - `train.py`: QLoRA;
  - `infer.py`: B and F outputs to JSONL.
- **Reuse:** `extract_wiki.SYSTEM`, `SCHEMA`, `verify_events`, `contract_statements` and `wiki_run`'s document
  builder.
- **The production extraction path isn't touched:** `scout/text/` gets no edits.

**Kept out of git** (added to `.gitignore`): `labeling/finetune/`, `models/finetune/` (adapters and checkpoints, under
the existing `models/`), `data/finetune/` (exported documents) and `*.safetensors`. Nothing goes to the Hugging Face
Hub unless the owner approves it and the licences allow it (§2).

**Public wording:**
- no README or CV claim until results exist;
- the word "production" is never used;
- numbers are reported exactly as measured.

**Hooks:** gitleaks and the other pre-commit hooks run on every commit. If one fails, work stops and the failure is
reported.

## Stages and time

| Stage | What | Owner's time | My time | Gate |
|---|---|---|---|---|
| 0 | This plan | Review | done | Approved 2026-11-24 (staged, 150 / 150 / 30, hand labels only, latency spend) |
| 1 | `scout/finetune/sample.py` and `labels.py` with tests, labelling guide, the three sets drawn and committed, test and dev sheets rendered, pre-registration in the research log. No new dependencies | — | done 2026-11-24 | Owner OK to start labelling |
| 2a | Hand labelling: test 150 and dev 30; 10% second pass on test | **about 12 h** | ~1 h | Labels done |
| 3 | `score.py` with tests; score C (no API calls); Claude live latency (~US$0.04); install the inference dependencies (each approved: torch, transformers, accelerate, bitsandbytes, plus the transitive safetensors, tokenizers and huggingface-hub); download Qwen3-4B at the pinned SHA; B on dev, then on test | Review | ~1 day, including about 1 GPU hour | Each dependency; compute choice |
| — | **Owner decides: stop here, or train** | Decision | — | Owner |
| 2b | Only if training: hand-label the train set (150) | about 10 h | ~1 h | Labels done |
| 4 | Only if training: install peft and trl (each approved; datasets only if needed); smoke run; training; F on dev and test | — | ~1 day, including about 2 GPU hours | Each dependency |
| 5 | Report, research-log result, SECURITY.md; PR for the owner to merge | Review | ~half a day | Owner merges |

**Total, staged.** To the decision point: about 12 h of the owner's labelling, about 1.5 days of my time and about
1 GPU hour. If training goes ahead: another 10 h of labelling, about 1.5 days of my time and about 2 GPU hours.
