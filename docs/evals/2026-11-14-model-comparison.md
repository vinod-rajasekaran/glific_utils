# Which Claude model should read the flows? (2026-11-14)

The org map makes one Claude call per page build. Claude reads the cleaned facts and writes the programmes, the stories and each flow's purpose, citing fact IDs as evidence. Everything else on the page is computed in Python: the graphs, numbers, links, starts and schedules. So the model choice only affects that one call. This compares Claude Opus 5.5, Sonnet 5.5 and Haiku 5.5 on it.

## Method

- **Input.** A real account with 44 active flows. Every model got the identical request (`claude_input.json`, about 52.5K input tokens): same prompt, same answer format, effort `high`. The comparison sent nothing new to Anthropic.
- **Runs.** Two per model, through the org map's own code. An answer that failed the checks would get one repair round.
- **Automatic checks.** The org map's validation counts the evidence problems in the first answer and what was dropped after repair. It also counts flows placed, programmes, parts and claims.
- **Quality.** Opus 5.5 judged all six answers in one call, against the same facts. The answers were labelled A–F in shuffled order, and the judge wasn't told which model wrote which. It scored each from 1 to 5 for accuracy (claims supported by the facts), usefulness (to a programme manager) and coverage (sensible, complete grouping). It also listed specific errors.
- **Reproduce.** `org_programme_architecture/compare_models.py RUN_DIR`, then `--judge`.

## Results

| Model | Cost per run | Time | Output tokens | Failed checks | Flows placed | Claims | Judge (accuracy / usefulness / coverage) | Judge rank |
|---|---|---|---|---|---|---|---|---|
| Opus 5.5 | $0.84 – $1.00 | 4.5 – 5.5 min | 34K – 37K | 0 | 44/44 | 84 – 104 | 5/5/5 and 4/5/4 | 1st, 2nd |
| Sonnet 5.5 | $0.37 – $0.38 | 2.5 min | ~16K | 0 | 44/44 | 72 – 76 | 4/4/4 and 4/4/4 | 3rd, 4th |
| Haiku 5.5 | $0.05 | 5.5 min | ~78K | 0 | 44/44 | 105 – 108 | 3/3/3 and 3/3/3 | 5th, 6th |

**What separated them.** The judge said every answer got the core journey right: registration, the daily data pull, the weekly nudges and their follow-ups, and the Q&A flow.

- **Opus** found the things a programme team would act on:
  - a test copy of a flow calls the wrong speech service;
  - open keywords let any contact trigger data syncs;
  - several flows have no tag;
  - one group is open to anyone.

  Its slips were one questionable grouping and one claim it overstated.
- **Sonnet** was accurate on the core, with minor slips: it double-counted one flow, contradicted itself once, and made one unsupported link. It noticed fewer of the less obvious issues.
- **Haiku** made factual errors. It said a flow has no schedule when the facts show four earlier ones, and gave flows roles the facts contradict. It also speculated without evidence, for example "a failed pull can send messages to the wrong contacts". It wrote the most claims, but more of them were wrong.

Every answer passed the automatic checks. Those checks catch IDs and evidence that don't exist, not claims that misread real evidence. Only the blind reading separated the models.

## Caveats

- One account and two runs per model.
- The judge was Opus, which may favour Opus's style. Its findings name specific claims you can check against the facts, and the ranking held across both runs of each model.
- Haiku took as long as Opus, because it thought for twice as many tokens. It's only cheaper, not faster.

## Decision

Keep **Opus 5.5** as the default. One page build costs about $1, and its answer goes to people making decisions about a programme, so accuracy matters most. `--model claude-sonnet-5-5` is available for cheaper, faster rebuilds, for example while you iterate. Haiku isn't recommended for this call. See [`../DECISIONS.md`](../DECISIONS.md).

Total cost of this comparison: about $3.60 (six runs, $2.68; judging, $0.93).
