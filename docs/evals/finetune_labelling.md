# Labelling guide: Wikipedia career events (fine-tuning experiment)

These labels are the ground truth for comparing Claude with a small local model ([FINETUNE_PLAN.md](../FINETUNE_PLAN.md)).
The rules are the ones the extraction prompt (`extract-v3`) gives the models, so the labels and the systems answer
the same question. Label what the text says, not what Claude or you would expect.

## Files

```sh
uv run --env-file .env python -m scout.finetune.labels render test   # once; also: render dev
uv run --env-file .env python -m scout.finetune.labels check test    # any time; lists every problem
```

- **Documents to read:** `labeling/finetune/test.md`. Each document shows the player, the snapshot date, a link to
  the Wikipedia diff, and the text with numbered lines.
- **Sheet to fill:** `labeling/finetune/test.csv`, with one row per document already in it. Add rows for documents
  with more than one event: copy the `doc_id` and number them in `row` (1, 2, 3, …).
- **Privacy:** both files hold Wikipedia text (CC BY-SA 4.0) and stay out of git. Don't share them.
- **Order:** label test first, then dev. Don't look at Claude's outputs for these documents while labelling.

## What counts as an event

| type | When |
|---|---|
| `injury` | An injury he suffered |
| `contract_extension` | He signed a new or extended contract with his current club |
| `contract_expiry` | His contract ran out, he left on a free, or his contract was terminated |
| `loan` | He joined a club on loan, or returned from a loan |
| `transfer` | A permanent move to another club |
| `none` | The document states none of the above: one row, every other column empty |

Rumours, interest, bids, speculation and planned moves that the text doesn't say happened don't count.

## Rules

1. **Only the text in front of you.** If you know something happened but the text doesn't say it, don't label it.
2. **Every event the text states, whenever it happened.** Don't skip events outside the year before the snapshot.
   The scorer applies the date window itself.
3. **`date`:** the date the text gives for the event, as `YYYY-MM-DD`, or `YYYY-MM` if only the month is stated, or
   `YYYY` if only the year is stated. Don't infer a missing part.
   - The year may come from the paragraph or from a season heading above the sentence ("2016–17"), but only when the
     text clearly carries it. If the line has no year, open the diff link to see the paragraph.
   - If the text gives no date at all, put the event in, leave `date` empty, and write `no date` in `note`.
4. **`contract_until`:** the contract's end date, only when the text states it ("until June 2017" → `2017-06`).
   Otherwise leave it empty.
5. **`injury_type`:** a few words, only when stated ("knee ligament", "hamstring"). **`duration_days`:** a whole
   number, only when the text gives a length ("six weeks" → 42). Otherwise leave both empty.
6. **`evidence`:** the shortest exact fragment that states the event, copied character for character, at most 300
   characters. If you give `contract_until`, the fragment must include the words that state it. The check rejects
   anything that isn't verbatim; extra or missing spaces are fine.
7. **One row per event.** "Joined on loan, then signed permanently" is two rows: `loan` and `transfer`. Returning from
   a loan and leaving again are two events.
8. **Hard cases go in `note`,** not into a forced label: an ambiguous date, an unclear loan or transfer, or a sentence
   you're unsure is about this player. Keep your best label and explain.

## Examples

| Text | Rows |
|---|---|
| "On 3 July 2019, he joined Leeds United on a season-long loan." | `loan`, `2019-07-03`, evidence `On 3 July 2019, he joined Leeds United on a season-long loan` |
| "In January 2020 he signed a new deal keeping him at the club until 2023." | `contract_extension`, `2020-01`, contract_until `2023`, evidence `In January 2020 he signed a new deal keeping him at the club until 2023` |
| "He was ruled out for six weeks after injuring his hamstring in March 2018." | `injury`, `2018-03`, injury_type `hamstring`, duration_days `42` |
| "Several clubs were reported to be interested in signing him." | Nothing. If the document has no other event: one `none` row |

## Time

About 4 minutes per document. The test documents have a median of 120 words, and many have no event. The 150 test
documents should take about 10 h and the 30 dev documents about 2 h. Stop whenever you like: `check` works on a
partly filled sheet, and the blank rows show what is left.
