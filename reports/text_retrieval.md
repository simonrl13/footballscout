# Does Wikipedia retrieval improve the agent's answers?

Paid run: commit `da74840`, model `claude-haiku-5-5`, 2026-10-15, API spend $0.058. This report: commit `32c6397`, the same responses replayed from the response cache ($0; every label identical), after one sentence of the contract section was corrected to the run's facts (see the research log). Pre-registration and decision rule: docs/RESEARCH_LOG.md (2026-10-15). A: the agent with search_text; B: the same agent without it. Labels are automatic (owner review of wrong/declined labels: docs/evals/text_review.md). 95% Wilson intervals.

## Released answers (primary)

| Condition | Group | n | Correct | Wrong (hallucinated) | Declined |
|---|---|---|---|---|---|
| A | all | 36 | 24/36 (67%, CI 50%–80%) | 1/36 (3%, CI 0%–14%) | 11/36 (31%, CI 18%–47%) |
| A | contract / high | 6 | 4/6 (67%, CI 30%–90%) | 0/6 (0%, CI 0%–39%) | 2/6 (33%, CI 10%–70%) |
| A | contract / low | 6 | 1/6 (17%, CI 3%–56%) | 0/6 (0%, CI 0%–39%) | 5/6 (83%, CI 44%–97%) |
| A | contract / mid | 6 | 3/6 (50%, CI 19%–81%) | 0/6 (0%, CI 0%–39%) | 3/6 (50%, CI 19%–81%) |
| A | transfer / high | 6 | 5/6 (83%, CI 44%–97%) | 1/6 (17%, CI 3%–56%) | 0/6 (0%, CI 0%–39%) |
| A | transfer / low | 6 | 5/6 (83%, CI 44%–97%) | 0/6 (0%, CI 0%–39%) | 1/6 (17%, CI 3%–56%) |
| A | transfer / mid | 6 | 6/6 (100%, CI 61%–100%) | 0/6 (0%, CI 0%–39%) | 0/6 (0%, CI 0%–39%) |
| A | high | 12 | 9/12 (75%, CI 47%–91%) | 1/12 (8%, CI 1%–35%) | 2/12 (17%, CI 5%–45%) |
| A | low | 12 | 6/12 (50%, CI 25%–75%) | 0/12 (0%, CI 0%–24%) | 6/12 (50%, CI 25%–75%) |
| A | mid | 12 | 9/12 (75%, CI 47%–91%) | 0/12 (0%, CI 0%–24%) | 3/12 (25%, CI 9%–53%) |
| B | all | 36 | 4/36 (11%, CI 4%–25%) | 0/36 (0%, CI 0%–10%) | 32/36 (89%, CI 75%–96%) |
| B | contract / high | 6 | 0/6 (0%, CI 0%–39%) | 0/6 (0%, CI 0%–39%) | 6/6 (100%, CI 61%–100%) |
| B | contract / low | 6 | 0/6 (0%, CI 0%–39%) | 0/6 (0%, CI 0%–39%) | 6/6 (100%, CI 61%–100%) |
| B | contract / mid | 6 | 0/6 (0%, CI 0%–39%) | 0/6 (0%, CI 0%–39%) | 6/6 (100%, CI 61%–100%) |
| B | transfer / high | 6 | 1/6 (17%, CI 3%–56%) | 0/6 (0%, CI 0%–39%) | 5/6 (83%, CI 44%–97%) |
| B | transfer / low | 6 | 1/6 (17%, CI 3%–56%) | 0/6 (0%, CI 0%–39%) | 5/6 (83%, CI 44%–97%) |
| B | transfer / mid | 6 | 2/6 (33%, CI 10%–70%) | 0/6 (0%, CI 0%–39%) | 4/6 (67%, CI 30%–90%) |
| B | high | 12 | 1/12 (8%, CI 1%–35%) | 0/12 (0%, CI 0%–24%) | 11/12 (92%, CI 65%–99%) |
| B | low | 12 | 1/12 (8%, CI 1%–35%) | 0/12 (0%, CI 0%–24%) | 11/12 (92%, CI 65%–99%) |
| B | mid | 12 | 2/12 (17%, CI 5%–45%) | 0/12 (0%, CI 0%–24%) | 10/12 (83%, CI 55%–95%) |

Paired comparison of correct answers: only A correct 20, only B correct 0, exact McNemar p = 0.000. Wrong answers: only A wrong 1, only B wrong 0, p = 1.000.

## Contract questions: released answers next to first drafts

In B no tool returns a contract year, so a year written from memory would fail the number check (retried, then blocked and counted as declined), and the system prompt already tells the model to copy every number from a tool. **The user-visible contract gap between A and B is therefore partly structural.** The first drafts, graded before the check, show what the model would have said. In this run 0 of 18 B contract answers reached the number check: the model declined before writing a year, so the structural part comes from the prompt's tools-only rules rather than the check itself.

| Condition | Level | Correct | Wrong (hallucinated) | Declined |
|---|---|---|---|---|
| A | released (user-visible) | 8/18 (44%, CI 25%–66%) | 0/18 (0%, CI 0%–18%) | 10/18 (56%, CI 34%–75%) |
| A | first draft | 8/18 (44%, CI 25%–66%) | 0/18 (0%, CI 0%–18%) | 10/18 (56%, CI 34%–75%) |
| B | released (user-visible) | 0/18 (0%, CI 0%–18%) | 0/18 (0%, CI 0%–18%) | 18/18 (100%, CI 82%–100%) |
| B | first draft | 0/18 (0%, CI 0%–18%) | 0/18 (0%, CI 0%–18%) | 18/18 (100%, CI 82%–100%) |

Sensitivity (pre-registered): transfer questions whose destination is not the player's demo club (get_player shows the current club in both conditions):

| Condition | Group | n | Correct | Wrong (hallucinated) | Declined |
|---|---|---|---|---|---|
| A | all | 13 | 12/13 (92%, CI 67%–99%) | 0/13 (0%, CI 0%–23%) | 1/13 (8%, CI 1%–33%) |
| A | transfer / high | 4 | 4/4 (100%, CI 51%–100%) | 0/4 (0%, CI 0%–49%) | 0/4 (0%, CI 0%–49%) |
| A | transfer / low | 5 | 4/5 (80%, CI 38%–96%) | 0/5 (0%, CI 0%–43%) | 1/5 (20%, CI 4%–62%) |
| A | transfer / mid | 4 | 4/4 (100%, CI 51%–100%) | 0/4 (0%, CI 0%–49%) | 0/4 (0%, CI 0%–49%) |
| A | high | 4 | 4/4 (100%, CI 51%–100%) | 0/4 (0%, CI 0%–49%) | 0/4 (0%, CI 0%–49%) |
| A | low | 5 | 4/5 (80%, CI 38%–96%) | 0/5 (0%, CI 0%–43%) | 1/5 (20%, CI 4%–62%) |
| A | mid | 4 | 4/4 (100%, CI 51%–100%) | 0/4 (0%, CI 0%–49%) | 0/4 (0%, CI 0%–49%) |
| B | all | 13 | 0/13 (0%, CI 0%–23%) | 0/13 (0%, CI 0%–23%) | 13/13 (100%, CI 77%–100%) |
| B | transfer / high | 4 | 0/4 (0%, CI 0%–49%) | 0/4 (0%, CI 0%–49%) | 4/4 (100%, CI 51%–100%) |
| B | transfer / low | 5 | 0/5 (0%, CI 0%–43%) | 0/5 (0%, CI 0%–43%) | 5/5 (100%, CI 57%–100%) |
| B | transfer / mid | 4 | 0/4 (0%, CI 0%–49%) | 0/4 (0%, CI 0%–49%) | 4/4 (100%, CI 51%–100%) |
| B | high | 4 | 0/4 (0%, CI 0%–49%) | 0/4 (0%, CI 0%–49%) | 4/4 (100%, CI 51%–100%) |
| B | low | 5 | 0/5 (0%, CI 0%–43%) | 0/5 (0%, CI 0%–43%) | 5/5 (100%, CI 57%–100%) |
| B | mid | 4 | 0/4 (0%, CI 0%–49%) | 0/4 (0%, CI 0%–49%) | 4/4 (100%, CI 51%–100%) |

## First drafts (before the number/citation check)

| Condition | Group | n | Correct | Wrong (hallucinated) | Declined |
|---|---|---|---|---|---|
| A | all | 36 | 24/36 (67%, CI 50%–80%) | 1/36 (3%, CI 0%–14%) | 11/36 (31%, CI 18%–47%) |
| A | contract / high | 6 | 4/6 (67%, CI 30%–90%) | 0/6 (0%, CI 0%–39%) | 2/6 (33%, CI 10%–70%) |
| A | contract / low | 6 | 1/6 (17%, CI 3%–56%) | 0/6 (0%, CI 0%–39%) | 5/6 (83%, CI 44%–97%) |
| A | contract / mid | 6 | 3/6 (50%, CI 19%–81%) | 0/6 (0%, CI 0%–39%) | 3/6 (50%, CI 19%–81%) |
| A | transfer / high | 6 | 5/6 (83%, CI 44%–97%) | 1/6 (17%, CI 3%–56%) | 0/6 (0%, CI 0%–39%) |
| A | transfer / low | 6 | 5/6 (83%, CI 44%–97%) | 0/6 (0%, CI 0%–39%) | 1/6 (17%, CI 3%–56%) |
| A | transfer / mid | 6 | 6/6 (100%, CI 61%–100%) | 0/6 (0%, CI 0%–39%) | 0/6 (0%, CI 0%–39%) |
| A | high | 12 | 9/12 (75%, CI 47%–91%) | 1/12 (8%, CI 1%–35%) | 2/12 (17%, CI 5%–45%) |
| A | low | 12 | 6/12 (50%, CI 25%–75%) | 0/12 (0%, CI 0%–24%) | 6/12 (50%, CI 25%–75%) |
| A | mid | 12 | 9/12 (75%, CI 47%–91%) | 0/12 (0%, CI 0%–24%) | 3/12 (25%, CI 9%–53%) |
| B | all | 36 | 4/36 (11%, CI 4%–25%) | 0/36 (0%, CI 0%–10%) | 32/36 (89%, CI 75%–96%) |
| B | contract / high | 6 | 0/6 (0%, CI 0%–39%) | 0/6 (0%, CI 0%–39%) | 6/6 (100%, CI 61%–100%) |
| B | contract / low | 6 | 0/6 (0%, CI 0%–39%) | 0/6 (0%, CI 0%–39%) | 6/6 (100%, CI 61%–100%) |
| B | contract / mid | 6 | 0/6 (0%, CI 0%–39%) | 0/6 (0%, CI 0%–39%) | 6/6 (100%, CI 61%–100%) |
| B | transfer / high | 6 | 1/6 (17%, CI 3%–56%) | 0/6 (0%, CI 0%–39%) | 5/6 (83%, CI 44%–97%) |
| B | transfer / low | 6 | 1/6 (17%, CI 3%–56%) | 0/6 (0%, CI 0%–39%) | 5/6 (83%, CI 44%–97%) |
| B | transfer / mid | 6 | 2/6 (33%, CI 10%–70%) | 0/6 (0%, CI 0%–39%) | 4/6 (67%, CI 30%–90%) |
| B | high | 12 | 1/12 (8%, CI 1%–35%) | 0/12 (0%, CI 0%–24%) | 11/12 (92%, CI 65%–99%) |
| B | low | 12 | 1/12 (8%, CI 1%–35%) | 0/12 (0%, CI 0%–24%) | 11/12 (92%, CI 65%–99%) |
| B | mid | 12 | 2/12 (17%, CI 5%–45%) | 0/12 (0%, CI 0%–24%) | 10/12 (83%, CI 55%–95%) |

## Claims supported by a cited source

| Condition | Claims (correct + wrong) | Supported by a cited passage | Owner to judge |
|---|---|---|---|
| A | 25 | 24 | 0 |
| B | 4 | 0 | 0 |

B cannot cite (search_text is withheld), so its claims are unsupported by construction.

## Limitations

- The system prompt is identical in both conditions, so in B it still describes search_text ("search_text returns passages from players' Wikipedia pages...") although the tool is withheld. The model may decline more readily in B, expecting a tool it doesn't have.
- Transfermarkt is the ground truth and can itself be wrong; the Wikipedia revisions are those in force on 12 June 2026 and may miss a recent move or extension.
- 36 questions (6 per type and band per condition): only large differences are detectable; per-band rows are descriptive.
- Labels are automatic until the owner's review of every wrong and declined label.

## Per question

| Question | Truth | Band | A | B | A draft | B draft |
|---|---|---|---|---|---|---|
| Which club did Matheus Cunha join in the summer 2018 transfer window? | Leipzig | high | correct | declined | correct | declined |
| Which club did Maximilian Beier join in the summer 2021 transfer window? | Hannover 96 | high | correct | declined | correct | declined |
| Which club did Milos Kerkez join in the summer 2023 transfer window? | Bournemouth | high | correct | declined | correct | declined |
| Which club did Eduardo Camavinga join in the summer 2021 transfer window? | Real Madrid | high | wrong | declined | wrong | declined |
| Which club did Djed Spence join in the summer 2021 transfer window? | Nott'm Forest | high | correct | declined | correct | declined |
| Which club did Martín Zubimendi join in the summer 2025 transfer window? | Arsenal | high | correct | correct | correct | correct |
| Which club did Lucas Chevalier join in the summer 2021 transfer window? | Valenciennes FC | mid | correct | declined | correct | declined |
| Which club did Andy Diouf join in the summer 2022 transfer window? | Basel | mid | correct | declined | correct | declined |
| Which club did Mohamed Salah join in the summer 2017 transfer window? | Liverpool | mid | correct | correct | correct | correct |
| Which club did Amine Gouiri join in the summer 2020 transfer window? | Nice | mid | correct | declined | correct | declined |
| Which club did Konstantinos Koulierakis join in the summer 2024 transfer window? | Wolfsburg | mid | correct | correct | correct | correct |
| Which club did Jordan Bos join in the summer 2023 transfer window? | KVC Westerlo | mid | correct | declined | correct | declined |
| Which club did Adrian Beck join in the summer 2018 transfer window? | SSV Ulm 1846 | low | correct | declined | correct | declined |
| Which club did Danny da Costa join in the summer 2017 transfer window? | Frankfurt | low | correct | declined | correct | declined |
| Which club did Mama Baldé join in the summer 2021 transfer window? | Troyes | low | correct | declined | correct | declined |
| Which club did Kilian Fischer join in the summer 2021 transfer window? | 1.FC Nuremberg | low | declined | declined | declined | declined |
| Which club did Guido Rodríguez join in the summer 2016 transfer window? | Club Tijuana | low | correct | declined | correct | declined |
| Which club did MT join in the summer 2022 transfer window? | Santa Clara | low | correct | correct | correct | correct |
| As of June 2026, until when does Kobbie Mainoo's contract with Manchester United run? | 2031 | high | correct | declined | correct | declined |
| As of June 2026, until when does Pape Matar Sarr's contract with Tottenham Hotspur run? | 2030 | high | correct | declined | correct | declined |
| As of June 2026, until when does Tom Bischof's contract with Bayern Munich run? | 2029 | high | correct | declined | correct | declined |
| As of June 2026, until when does Cole Palmer's contract with Chelsea FC run? | 2033 | high | correct | declined | correct | declined |
| As of June 2026, until when does Dango Ouattara's contract with Brentford FC run? | 2030 | high | declined | declined | declined | declined |
| As of June 2026, until when does Luis Díaz's contract with Bayern Munich run? | 2029 | high | declined | declined | declined | declined |
| As of June 2026, until when does Viktor Tsygankov's contract with Girona FC run? | 2027 | mid | correct | declined | correct | declined |
| As of June 2026, until when does Facundo Medina's contract with Olympique Marseille run? | 2030 | mid | declined | declined | declined | declined |
| As of June 2026, until when does Josh King's contract with Fulham FC run? | 2029 | mid | correct | declined | correct | declined |
| As of June 2026, until when does Oumar Solet's contract with Udinese Calcio run? | 2027 | mid | declined | declined | declined | declined |
| As of June 2026, until when does Ethan Mbappé's contract with LOSC Lille run? | 2027 | mid | correct | declined | correct | declined |
| As of June 2026, until when does Hugo Sotelo's contract with Celta de Vigo run? | 2028 | mid | declined | declined | declined | declined |
| As of June 2026, until when does Thiago Balieiro's contract with Vitória Guimarães SC run? | 2029 | low | declined | declined | declined | declined |
| As of June 2026, until when does Pedro Bondo's contract with FC Famalicão run? | 2029 | low | correct | declined | correct | declined |
| As of June 2026, until when does Lilian Raolisoa's contract with Angers SCO run? | 2028 | low | declined | declined | declined | declined |
| As of June 2026, until when does Tiago Manso's contract with CD Tondela run? | 2027 | low | declined | declined | declined | declined |
| As of June 2026, until when does Casper Widell's contract with Excelsior Rotterdam run? | 2027 | low | declined | declined | declined | declined |
| As of June 2026, until when does Evert Linthorst's contract with Go Ahead Eagles run? | 2028 | low | declined | declined | declined | declined |
