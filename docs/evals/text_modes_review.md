# Text experiment (retrieval modes): answers to review, blind to mode

Commit `3fd76c1`. Every answer labelled wrong or declined (released or draft), shuffled, with no mode shown; the key is in reports/text_exp_modes.json (`review_key`): don't open it before the review is done.

**Reviewed by the owner on 2026-11-13: 24/24 automatic labels right.** Marks and notes below are the owner's. Mark each automatic label right or wrong; for wrong transfer claims, also whether a cited passage supports the club named.

## R01: declined

**Q:** Which club did Mohamed Salah join in the summer 2017 transfer window?  
**Truth:** Liverpool  
**Review:** [x] label right  [ ] label wrong  
**Note:** Scope refusal ("only market values"), unlike every other answer, which uses the tools. It's a decline, but a behaviour bug: transfer questions are in scope for this experiment. The distinctive wording may also unblind the mode.

> I can only answer questions about football players' Transfermarkt market values and the model's 12-month value forecasts, so I can't answer this one. I can look up a player's current market value, forecast, or comparison with other players if you'd like.

## R02: declined

**Q:** Which club did Kilian Fischer join in the summer 2021 transfer window?  
**Truth:** 1.FC Nuremberg  
**Review:** [x] label right  [ ] label wrong  
**Note:** 2021 move missing from passages in both runs, probably a retrieval recall miss.

> I couldn't find a summer 2021 transfer for Kilian Fischer in the sources I checked, so I can't name a club for that window.
> 
> What the Wikipedia text does say (revision of 9 February 2026):
> - He joined Türkgücü München in July 2019 and extended his contract there the following summer. [wiki 1]
> - On 10 June 2022 he signed a five-year contract with VfL Wolfsburg, where he plays now. [wiki 2]
> 
> Nothing in the passages covers a move in 2021. The page may simply omit it, so a club's official announcement or a transfer database would be the best place to confirm.
> 
> Sources (Wikipedia, public text, not model output):
> [wiki 1] Kilian Fischer's Wikipedia page, revision of 2026-02-09: https://en.wikipedia.org/w/index.php?oldid=1337381237 (authors: https://en.wikipedia.org/w/index.php?title=Kilian+Fischer&action=history)
> [wiki 2] Kilian Fischer's Wikipedia page, revision of 2026-02-09: https://en.wikipedia.org/w/index.php?oldid=1337381237 (authors: https://en.wikipedia.org/w/index.php?title=Kilian+Fischer&action=history)
> Wikipedia text is available under CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/

## R03: declined

**Q:** As of June 2026, until when does Evert Linthorst's contract with Go Ahead Eagles run?  
**Truth:** 2028  
**Review:** [x] label right  [ ] label wrong  
**Note:** Wikipedia is stale (gives 2025/26, truth is 2028), so the decline is correct.

> I can't confirm the exact end date from the tools. Wikipedia's page (revision of 22 May 2026) says that in October 2023 Linthorst signed a one-year contract extension with Go Ahead Eagles, "with the option of an additional season." It doesn't give the resulting expiry date, and I don't have a more recent contract source. [wiki 1] For the exact date, check Transfermarkt or the club's website.
> 
> Data as of 12 June 2026.
> 
> Sources (Wikipedia, public text, not model output):
> [wiki 1] Evert Linthorst's Wikipedia page, revision of 2026-05-22: https://en.wikipedia.org/w/index.php?oldid=1355509754 (authors: https://en.wikipedia.org/w/index.php?title=Evert+Linthorst&action=history)
> Wikipedia text is available under CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/

## R04: declined

**Q:** As of June 2026, until when does Thiago Balieiro's contract with Vitória Guimarães SC run?  
**Truth:** 2029  
**Review:** [x] label right  [ ] label wrong

> I couldn't find the end date of Thiago Balieiro's contract with Vitória Guimarães SC. The player profile in my data (data as of 12 June 2026) lists his club, position and market value, but no contract expiry. My Wikipedia search also returned no passage about his contract. Check Transfermarkt or the club's website for the current expiry date.

## R05: declined

**Q:** As of June 2026, until when does Dango Ouattara's contract with Brentford FC run?  
**Truth:** 2030  
**Review:** [x] label right  [ ] label wrong  
**Note:** Borderline. No year is committed, but "late 2020s" is wrong: 5 years from Aug 2025 is 2030. 2030 could be derived from the cited passage (missed answer).

> I can't confirm the exact expiry date. Wikipedia says Ouattara joined Brentford on 16 August 2025 "on a five-year contract, with the option of a further year." [wiki 1] That points to a deal running into the late 2020s, but the passage doesn't give the end date, and my tools don't return contract expiry data. Checking the club or Transfermarkt would give the exact date.
> 
> Data as of 12 June 2026. His Transfermarkt market value is €35.0m (valuation date 3 June 2026), a crowd estimate, not a transfer fee. The model forecasts a 2.8% change over the next 12 months, with an 80% interval of -29.1% to 84.6%.
> 
> Sources (Wikipedia, public text, not model output):
> [wiki 1] Dango Ouattara's Wikipedia page, revision of 2026-06-08: https://en.wikipedia.org/w/index.php?oldid=1358391561 (authors: https://en.wikipedia.org/w/index.php?title=Dango+Ouattara&action=history)
> Wikipedia text is available under CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/

## R06: declined

**Q:** As of June 2026, until when does Hugo Sotelo's contract with Celta de Vigo run?  
**Truth:** 2028  
**Review:** [x] label right  [ ] label wrong

> I couldn't find Hugo Sotelo's contract end date in the data I have access to.
> 
> The player profile for Hugo Sotelo (Celta de Vigo, LaLiga) doesn't include contract information, and the Wikipedia passages I searched don't mention when his contract runs until. The passages cover his academy background, his senior debut in May 2021, and his current club. [wiki 1] [wiki 2]
> 
> For the exact expiry date, check Celta de Vigo's official website or Transfermarkt's player profile.
> 
> Sources (Wikipedia, public text, not model output):
> [wiki 1] Hugo Sotelo's Wikipedia page, revision of 2026-05-30: https://en.wikipedia.org/w/index.php?oldid=1356844842 (authors: https://en.wikipedia.org/w/index.php?title=Hugo+Sotelo&action=history)
> [wiki 2] Hugo Sotelo's Wikipedia page, revision of 2026-05-30: https://en.wikipedia.org/w/index.php?oldid=1356844842 (authors: https://en.wikipedia.org/w/index.php?title=Hugo+Sotelo&action=history)
> Wikipedia text is available under CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/

## R07: declined

**Q:** As of June 2026, until when does Luis Díaz's contract with Bayern Munich run?  
**Truth:** 2029  
**Review:** [x] label right  [ ] label wrong  
**Note:** 2029 could be derived from the cited passage (4-year deal, July 2025). Over-cautious decline.

> Luis Díaz's exact contract expiry date isn't in my data. Wikipedia says he signed a **four-year deal** with Bayern Munich on 30 July 2025, for a reported fee of €75 million including add-ons [wiki 1]. The fee is a reported figure, not a confirmed one. For the exact end date, check Bayern's official site or a transfer database.
> 
> Data as of 12 June 2026.
> 
> Sources (Wikipedia, public text, not model output):
> [wiki 1] Luis Díaz's Wikipedia page, revision of 2026-06-02: https://en.wikipedia.org/w/index.php?oldid=1357375545 (authors: https://en.wikipedia.org/w/index.php?title=Luis+D%C3%ADaz+%28footballer%2C+born+1997%29&action=history)
> Wikipedia text is available under CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/

## R08: declined

**Q:** Which club did Kilian Fischer join in the summer 2021 transfer window?  
**Truth:** 1.FC Nuremberg  
**Review:** [x] label right  [ ] label wrong  
**Note:** The hedge "may have stayed at Türkgücü" is wrong (truth: Nuremberg), but no club is asserted. 2021 move missing from passages in both runs, probably a retrieval recall miss.

> I couldn't find a summer 2021 transfer for Kilian Fischer. The Wikipedia passages I found don't mention one. They say he joined Türkgücü München in July 2019 and extended his contract there the following summer [wiki 1]. He then signed a five-year contract with VfL Wolfsburg on 10 June 2022 [wiki 2]. The passages don't say what happened in the 2021 window, so he may have stayed at Türkgücü, but I can't confirm that from these sources.
> 
> He is currently a Wolfsburg player in the Bundesliga. The Transfermarkt market value is €4.0m (valuation date 27 May 2026, data as of 12 June 2026). That is a crowd estimate, not a transfer fee.
> 
> Sources (Wikipedia, public text, not model output):
> [wiki 1] Kilian Fischer's Wikipedia page, revision of 2026-02-09: https://en.wikipedia.org/w/index.php?oldid=1337381237 (authors: https://en.wikipedia.org/w/index.php?title=Kilian+Fischer&action=history)
> [wiki 2] Kilian Fischer's Wikipedia page, revision of 2026-02-09: https://en.wikipedia.org/w/index.php?oldid=1337381237 (authors: https://en.wikipedia.org/w/index.php?title=Kilian+Fischer&action=history)
> Wikipedia text is available under CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/

## R09: declined

**Q:** As of June 2026, until when does Tiago Manso's contract with CD Tondela run?  
**Truth:** 2027  
**Review:** [x] label right  [ ] label wrong

> I couldn't find the end date of Tiago Manso's contract with CD Tondela. The player data I can access (as of 12 June 2026) covers his club, position, age and market value, but not contract terms. I also searched his English Wikipedia page and found no passage mentioning his contract. To check, you could use Transfermarkt's player profile or the club's official site.
> 
> Tiago Manso is a 26.5-year-old right-back listed at CD Tondela in Liga Portugal. His Transfermarkt market value is €0.9m (valuation date 28 May 2026; data as of 12 June 2026). Market values are crowd estimates, not transfer fees.

## R10: declined

**Q:** As of June 2026, until when does Luis Díaz's contract with Bayern Munich run?  
**Truth:** 2029  
**Review:** [x] label right  [ ] label wrong  
**Note:** 2029 could be derived (4-year deal from July 2025). Also: "central estimate, not a prediction" contradicts itself.

> I can't find the exact expiry date in my data. The Wikipedia page (revision dated 2 June 2026) says Díaz signed a **four-year deal** with Bayern Munich on 30 July 2025, but it doesn't state the end date. [wiki 1] You could check Bayern's official site or Transfermarkt to confirm it.
> 
> For context, the Transfermarkt market value is €70.0m (valuation date 27 May 2026). That is a crowd estimate, not a transfer fee. Data as of 12 June 2026. The model forecasts a 12-month change of -20.7%, with an 80% interval of -43.6% to +2.6%. This is the model's central estimate, not a prediction of his actual value.
> 
> Sources (Wikipedia, public text, not model output):
> [wiki 1] Luis Díaz's Wikipedia page, revision of 2026-06-02: https://en.wikipedia.org/w/index.php?oldid=1357375545 (authors: https://en.wikipedia.org/w/index.php?title=Luis+D%C3%ADaz+%28footballer%2C+born+1997%29&action=history)
> Wikipedia text is available under CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/

## R11: declined

**Q:** As of June 2026, until when does Evert Linthorst's contract with Go Ahead Eagles run?  
**Truth:** 2028  
**Review:** [x] label right  [ ] label wrong  
**Note:** Wikipedia is stale here (extension + option gives 2025/26, truth is 2028), so the decline is correct.

> I can't confirm when Evert Linthorst's contract with Go Ahead Eagles runs until. The player profile doesn't include contract end dates, and the Wikipedia text I found doesn't state the current one.
> 
> What the Wikipedia page (revision of 22 May 2026) does say is that in January 2022 he signed a two-and-a-half-year deal running to the summer of 2024. In October 2023 he signed a one-year extension with the club, with the option of an additional season. [wiki 1] The page doesn't say whether that option was taken up, so the current end date is unconfirmed. The club or Transfermarkt would be the best places to check.
> 
> For reference, his Transfermarkt market value is €1.2m (valuation date 28 May 2026, data as of 12 June 2026). This is a crowd estimate, not a transfer fee.
> 
> Sources (Wikipedia, public text, not model output):
> [wiki 1] Evert Linthorst's Wikipedia page, revision of 2026-05-22: https://en.wikipedia.org/w/index.php?oldid=1355509754 (authors: https://en.wikipedia.org/w/index.php?title=Evert+Linthorst&action=history)
> Wikipedia text is available under CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/

## R12: declined

**Q:** As of June 2026, until when does Facundo Medina's contract with Olympique Marseille run?  
**Truth:** 2030  
**Review:** [x] label right  [ ] label wrong  
**Note:** Claims the "until 2026" line "is a 2023 edit". It is the 2026 revision describing a 2023 event, so the claim is unsupported.

> The tools don't give Facundo Medina's contract end date at Marseille, so I can't confirm it.
> 
> What I can see:
> - Wikipedia (revision of 10 June 2026) describes him as a centre-back on loan at Marseille from Lens. [wiki 1]
> - The only end date in the passages is from a January 2023 extension with Lens, "until 2026". [wiki 2] That refers to his Lens deal, and it is a 2023 edit, so it may be out of date.
> 
> The loan end date is not in the sources I can access. Marseille's or Lens's official club announcements would be the place to check.
> 
> Sources (Wikipedia, public text, not model output):
> [wiki 1] Facundo Medina's Wikipedia page, revision of 2026-06-10: https://en.wikipedia.org/w/index.php?oldid=1358769281 (authors: https://en.wikipedia.org/w/index.php?title=Facundo+Medina&action=history)
> [wiki 2] Facundo Medina's Wikipedia page, revision of 2026-06-10: https://en.wikipedia.org/w/index.php?oldid=1358769281 (authors: https://en.wikipedia.org/w/index.php?title=Facundo+Medina&action=history)
> Wikipedia text is available under CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/

## R13: declined

**Q:** As of June 2026, until when does Lilian Raolisoa's contract with Angers SCO run?  
**Truth:** 2028  
**Review:** [x] label right  [ ] label wrong  
**Note:** Cites a Wikipedia revision but has no Sources block (citation/licence missing).

> I can't find Lilian Raolisoa's contract end date in my tools, so I can't tell you when his deal with Angers runs until.
> 
> The data I can access covers his club (Angers SCO, Ligue 1), position (right-back), and age (26), but not contract terms. His English Wikipedia page, as of its 20 May 2026 revision, describes his Angers career but doesn't mention a contract end date. For the exact date, check Angers' official site or Transfermarkt.

## R14: declined

**Q:** As of June 2026, until when does Hugo Sotelo's contract with Celta de Vigo run?  
**Truth:** 2028  
**Review:** [x] label right  [ ] label wrong

> I can't find Hugo Sotelo's contract end date. The player profile I can access (data as of 12 June 2026) lists him as a Celta de Vigo central midfielder, but it has no contract information. His English Wikipedia page, as of its 30 May 2026 revision, confirms he is a Celta de Vigo player but doesn't mention his contract terms [wiki 1]. For the expiry date, check Celta de Vigo's official site or Transfermarkt.
> 
> Sources (Wikipedia, public text, not model output):
> [wiki 1] Hugo Sotelo's Wikipedia page, revision of 2026-05-30: https://en.wikipedia.org/w/index.php?oldid=1356844842 (authors: https://en.wikipedia.org/w/index.php?title=Hugo+Sotelo&action=history)
> Wikipedia text is available under CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/

## R15: declined

**Q:** Which club did MT join in the summer 2022 transfer window?  
**Truth:** Santa Clara  
**Review:** [x] label right  [ ] label wrong  
**Note:** Clarification request, not a decline. The item itself is bad: "MT" is not a usable player name. Fix or drop it from the eval set.

> I can't tell which player "MT" is. Could you give me the full name? If you know the club or league, that would help too. Once I have the name, I can look up the player's transfer history from their Wikipedia page.

## R16: declined

**Q:** As of June 2026, until when does Lilian Raolisoa's contract with Angers SCO run?  
**Truth:** 2028  
**Review:** [x] label right  [ ] label wrong

> I couldn't find Lilian Raolisoa's contract end date with Angers SCO. My tools don't include contract expiry dates, and the Wikipedia passages I found don't mention one.
> 
> What I can confirm: he is in the data as an Angers SCO right-back, aged 26. His Transfermarkt market value is €4.0m, with a valuation date of 1 June 2026 (data as of 12 June 2026). That value is a crowd estimate, not a transfer fee. For his contract end date, check Transfermarkt or Angers SCO's official website.

## R17: declined

**Q:** As of June 2026, until when does Casper Widell's contract with Excelsior Rotterdam run?  
**Truth:** 2027  
**Review:** [x] label right  [ ] label wrong

> I couldn't find the end date of Casper Widell's contract with Excelsior Rotterdam. Neither the player data nor the Wikipedia passages I searched state it. The most recent Wikipedia revision I found (18 May 2026) only confirms that he now plays for Excelsior, and its contract reference covers his earlier Helsingborg deal, which ran until 2023 [wiki 1].
> 
> For the current expiry date, check Excelsior Rotterdam's official site or Transfermarkt.
> 
> Other data for him (data as of 12 June 2026): he is a 23-year-old Swedish centre-back, with a Transfermarkt market value of €1.5m (valuation date 28 May 2026). That value is a crowd estimate, not a transfer fee. The model forecasts a 10.8% change over the next 12 months, with an 80% interval of -33.9% to 84.6%.
> 
> Sources (Wikipedia, public text, not model output):
> [wiki 1] Casper Widell's Wikipedia page, revision of 2026-05-18: https://en.wikipedia.org/w/index.php?oldid=1354896647 (authors: https://en.wikipedia.org/w/index.php?title=Casper+Widell&action=history)
> Wikipedia text is available under CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/

## R18: declined

**Q:** As of June 2026, until when does Oumar Solet's contract with Udinese Calcio run?  
**Truth:** 2027  
**Review:** [x] label right  [ ] label wrong

> I couldn't find Oumar Solet's contract end date in the data I have. The player profile shows he plays for Udinese Calcio, but it doesn't include contract expiry, and the Wikipedia passages I searched don't state one [wiki 1]. The Wikipedia text I found covers his pre-contract with Udinese in October 2024 and his move to the club in January 2025 [wiki 2], but not how long the deal runs. You could check Transfermarkt or the club's official site.
> 
> For reference, his market value is €23.0m (Transfermarkt crowd estimate, not a transfer fee; valuation date 29 May 2026, data as of 12 June 2026).
> 
> Sources (Wikipedia, public text, not model output):
> [wiki 1] Oumar Solet's Wikipedia page, revision of 2026-06-05: https://en.wikipedia.org/w/index.php?oldid=1357997249 (authors: https://en.wikipedia.org/w/index.php?title=Oumar+Solet&action=history)
> [wiki 2] Oumar Solet's Wikipedia page, revision of 2026-06-05: https://en.wikipedia.org/w/index.php?oldid=1357997249 (authors: https://en.wikipedia.org/w/index.php?title=Oumar+Solet&action=history)
> Wikipedia text is available under CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/

## R19: declined

**Q:** As of June 2026, until when does Oumar Solet's contract with Udinese Calcio run?  
**Truth:** 2027  
**Review:** [x] label right  [ ] label wrong  
**Note:** Garbled sentence: "The club sources he was on a pre-contract...".

> I couldn't find Oumar Solet's contract end date in my tools, so I can't tell you as of June 2026 when his Udinese deal runs until.
> 
> The player data I can access (data as of 12 June 2026) lists him at Udinese Calcio, but it has no contract field. Wikipedia passages I searched confirm his Udinese move but don't give an expiry date. The passages cover his pre-contract signed on 1 October 2024 and his debut on 4 January 2025 [wiki 1]. The club sources he was on a pre-contract from October 2024 with a 1 January 2025 start, but I did not find the length of the agreement.
> 
> For the exact expiry, check Udinese's official site or Transfermarkt.
> 
> Sources (Wikipedia, public text, not model output):
> [wiki 1] Oumar Solet's Wikipedia page, revision of 2026-06-05: https://en.wikipedia.org/w/index.php?oldid=1357997249 (authors: https://en.wikipedia.org/w/index.php?title=Oumar+Solet&action=history)
> Wikipedia text is available under CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/

## R20: declined

**Q:** As of June 2026, until when does Thiago Balieiro's contract with Vitória Guimarães SC run?  
**Truth:** 2029  
**Review:** [x] label right  [ ] label wrong

> I couldn't find Thiago Balieiro's contract end date in the data. The player profile doesn't include contract details, and no Wikipedia passage I searched mentions his contract.
> 
> He is listed as a centre-back at Vitória Guimarães SC, aged 23.3, with a Transfermarkt market value of €1.0m (valuation date 28 May 2026; data as of 12 June 2026). Market values are crowd estimates, not transfer fees. For the contract end date, the club's website or Transfermarkt's contract section would be the best places to check.

## R21: declined

**Q:** As of June 2026, until when does Tiago Manso's contract with CD Tondela run?  
**Truth:** 2027  
**Review:** [x] label right  [ ] label wrong

> I couldn't find Tiago Manso's contract end date with CD Tondela. My player data (as of 12 June 2026) has his club and market value but no contract expiry, and I found no matching passages on his Wikipedia page.
> 
> What I can confirm: he is a 26.5-year-old right-back at CD Tondela in Liga Portugal, with a Transfermarkt market value of €0.9m (valuation date 28 May 2026). That value is a crowd estimate, not a transfer fee. For the contract date, Transfermarkt's player profile or the club's website would be the best places to check.

## R22: declined

**Q:** As of June 2026, until when does Dango Ouattara's contract with Brentford FC run?  
**Truth:** 2030  
**Review:** [x] label right  [ ] label wrong  
**Note:** 2030 could be derived from the cited passage (5-year deal, Aug 2025).

> The tools don't give an exact end date for Dango Ouattara's Brentford contract. As of 12 June 2026, Wikipedia says he joined Brentford on 16 August 2025 on a five-year contract, with the option of a further year. [wiki 1] (Wikipedia revision dated 8 June 2026.) The exact expiry date isn't stated in that passage, so check Brentford's official site or a transfer database for the precise date.
> 
> The platform's data (as of 12 June 2026) lists him at a Transfermarkt market value of €35.0m (valuation date 3 June 2026). Market values are crowd estimates, not transfer fees.
> 
> Sources (Wikipedia, public text, not model output):
> [wiki 1] Dango Ouattara's Wikipedia page, revision of 2026-06-08: https://en.wikipedia.org/w/index.php?oldid=1358391561 (authors: https://en.wikipedia.org/w/index.php?title=Dango+Ouattara&action=history)
> Wikipedia text is available under CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/

## R23: declined

**Q:** As of June 2026, until when does Casper Widell's contract with Excelsior Rotterdam run?  
**Truth:** 2027  
**Review:** [x] label right  [ ] label wrong

> I couldn't find Casper Widell's contract end date at Excelsior Rotterdam. Our player data doesn't include contract details, and the Wikipedia passages I searched only cover his earlier Helsingborg deal, which ran until 2023 [wiki 1]. Wikipedia's page (revision of 18 May 2026) describes him as a centre-back for Excelsior but gives no end date for the current deal. For the current expiry, check Excelsior's official site or Transfermarkt.
> 
> For context, data as of 12 June 2026 shows his Transfermarkt market value as €1.5m (valuation date 28 May 2026). This is a crowd estimate, not a transfer fee. The model forecasts a central change of 10.8% over the next 12 months, with an 80% interval of -33.9% to 84.6%.
> 
> Sources (Wikipedia, public text, not model output):
> [wiki 1] Casper Widell's Wikipedia page, revision of 2026-05-18: https://en.wikipedia.org/w/index.php?oldid=1354896647 (authors: https://en.wikipedia.org/w/index.php?title=Casper+Widell&action=history)
> Wikipedia text is available under CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/

## R24: declined

**Q:** As of June 2026, until when does Facundo Medina's contract with Olympique Marseille run?  
**Truth:** 2030  
**Review:** [x] label right  [ ] label wrong

> I can't find the end date of Facundo Medina's contract with Olympique Marseille in my tools.
> 
> What I can confirm: Wikipedia describes him as playing for Marseille on loan from Lens (revision of 10 June 2026) [wiki 1]. His Lens contract was extended in January 2023 "until 2026" [wiki 2]. That is the Lens deal, not the Marseille one, and the Wikipedia text may be outdated.
> 
> For the Marseille contract end date, check Transfermarkt or the club's website.
> 
> For context, Transfermarkt's crowd estimate of his market value is EUR 18.0m (valuation date 1 June 2026; data as of 12 June 2026). That is not a transfer fee.
> 
> Sources (Wikipedia, public text, not model output):
> [wiki 1] Facundo Medina's Wikipedia page, revision of 2026-06-10: https://en.wikipedia.org/w/index.php?oldid=1358769281 (authors: https://en.wikipedia.org/w/index.php?title=Facundo+Medina&action=history)
> [wiki 2] Facundo Medina's Wikipedia page, revision of 2026-06-10: https://en.wikipedia.org/w/index.php?oldid=1358769281 (authors: https://en.wikipedia.org/w/index.php?title=Facundo+Medina&action=history)
> Wikipedia text is available under CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/

