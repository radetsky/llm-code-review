# Evaluation on golden cases

This folder measures how well the review engines find problems.

## Run

    python -m evaluation.run_eval --list
    python -m evaluation.run_eval --runs 5
    python -m evaluation.run_eval --engines agent --cases ctx-wrong-unit --runs 3
    python -m evaluation.run_eval --engines classic,hybrid,agent --runs 3

The engines are `classic`, `hybrid` and `agent`. A prompt variant runs through `--config` with
`prompt.custom_prompt`, so you can compare two prompts with the same cases.

The script needs `LLM_API_KEY` and `LLM_BASE_URL` in the environment. It
saves `report.md` and `runs.json` in `evaluation/results/<time>`. Git
ignores that folder.

## Cost on real changes

The golden cases are small. To see the cost on real changes, run

    python -m evaluation.history --per-bucket 3

The tool picks changes from the git history of the repository in four size classes (small, medium,
large and huge, by the number of changed lines in files that the review reads). It runs the
engines on them and writes a report with the time, the tokens, the steps, the reviews that hit a
budget, the fallbacks and the number of findings. It has no answer key, so read the findings in
`runs.json` to judge them. The tool sends the code of the repository to the LLM that you configure.

## Cases

A case is a folder in `evaluation/cases`.

- `before/` holds the files before the change.
- `after/` holds the full tree after the change.
- `expected.json` lists the problems that a correct review finds.

An expected problem has a file, a regular expression and a severity. The
loader finds the line of the first match in the file after the change.
A case with an empty list is a clean case. A correct review reports no
critical issue and no warning for it.

Rules for a new case:

- Do not write words in the code that tell where the problem is.
- Use fake data only. Do not use text that looks like a real key.
- Put a case in one of these groups: a problem in the diff, a problem that
  needs code outside the diff, a problem inside a large change, or a clean
  change that looks risky.

## Metrics

- Recall: the share of expected problems that a finding hits (the line
  distance is 2 lines or less).
- Precision: the share of critical issues and warnings that hit an
  expected problem.
- A false positive is a critical issue or a warning that hits no expected
  problem. Read the findings in `runs.json`. Some false positives are
  correct remarks that the case did not plan.
- The classic engine does not report tokens or steps.
