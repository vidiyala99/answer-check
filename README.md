# answer-check

A docs assistant can hand its model a wrong code snippet, or the model can invent an argument, and the answer
still reads fine. `answer-check` catches that before the answer reaches the user. It parses the Python code blocks in a
drafted answer, finds the SDK calls, and checks each one against signatures read from the SDK's own source.
For each call it returns a verdict and a one-line repair hint you can feed back to the model for one retry.

No LLM inside. Nothing from the SDK is imported or run: signatures come from parsing the source with `ast`.
Standard library only (tested on Python 3.12.10).

## What it found (WorkOS Python SDK 10.9.0)

**The docs.** 844 public docs pages, 2,135 Python blocks, 2,093 SDK calls:

| verdict | calls |
|---|---|
| ok | 1,405 |
| wrong-arg (would raise `TypeError`) | 546 across 80 methods on 188 pages |
| unknown-method (would raise `AttributeError`) | 142 |

459 of the 546 wrong-arg calls pass `id_=` where the SDK takes `id`. The docs snippets come from a generator that
renames `id` to `id_`, while the SDK generator keeps `id`. A fix for that generator is open upstream (not merged yet):
[workos/oagen-emitters#318](https://github.com/workos/oagen-emitters/pull/318).

A 15-call random hand sample of the flags (seed in `drift/`) was checked against the SDK source: 15/15 verdicts
right. Full list: `drift/corpus.json`; summary: `drift/corpus-summary.txt`.

**The assistant.** 40 questions to the public WorkOS docs assistant, each asking for one Python SDK call: 20 about
methods whose docs are wrong, 20 about methods whose docs are right. Each answer was hand-labeled against the SDK
source *before* the checker ran (`eval/hand-labels.json`).

| | |
|---|---|
| answers that would fail | 20 of 40 (18 of the drifted 20, 2 of the clean 20) |
| caught by answer-check | 20 of 20 |
| missed | 0 |
| false flags on the 20 working answers | 0 |
| broken answers repeating a wrong argument from the assistant's own tool output (docs snippets) | 11 of 20 |
| broken answers inventing an argument no tool returned | 9 of 20 |

Per-question verdicts and hints: `eval/score.json`. The answers themselves are not redistributed here.

Read these numbers with their limits: every question named the method, so the answers were short and on target.
A free-form question gives the checker more prose and fewer calls. And the checker knows signatures, not intent:
when the assistant passed `token` and `new_password` to `reset_password`, the hint correctly says `email` is
required, but the user almost certainly wanted `confirm_password_reset`.

## Where it sits

```
question -> retrieve -> draft answer -> answer-check -> ok: stream as is
                                              |
                                              +-> wrong-arg / unknown-method:
                                                  one repair turn with the hints, check again, then stream
```

It is one `ast.parse` per code block and no model call, so it can sit between
generation and the end of the stream. Rebuild the index on each SDK release.

## Use

```sh
# build a signature index from SDK source (static; nothing is imported)
python -m answer_check index path/to/workos-python/src/workos --version 10.9.0 -o data/index-python-10.9.0.json

# check an answer: Markdown, or a JSON record with an "answer" field. Exit 1 = a call would fail.
python -m answer_check check --index data/index-python-10.9.0.json examples/drafted_answer.md

python -m unittest discover -s tests -t .
```

On `examples/drafted_answer.md` it reports:

```
user_management.get_user     wrong-arg  `id_` is not a parameter; use `id`.
user_management.update_user  wrong-arg  `user_id` is not a parameter; `id` is required.
```

From Python: `from answer_check.check import check_answer; check_answer(markdown_text, index)`.

## Verdicts

- `ok`: the call binds to the signature.
- `wrong-arg`: unknown keyword (with the closest real name when there is one), missing required argument,
  too many positional arguments, or a keyword-only argument passed by position.
- `unknown-method`: the accessor or method does not exist. When another resource has that method, the hint
  names it (for example `client.pipes...` instead of a non-existent accessor).
- `not-checked`: arguments are unpacked with `*` or `**`, so names cannot be checked statically.

Calls on receivers it cannot trace to the client are skipped, not reported.

Inherited methods are resolved through base classes, `async` clients use their async accessors, and client
variables are traced from `WorkOSClient(...)` assignments.

## Not covered

Python only. It checks that calls bind, not that values are right (an ID of the wrong kind still passes).
Return values and attribute use on results are not checked.

## Layout

```
answer_check/   sigindex.py (SDK source -> index), check.py (answer -> verdicts), CLI
data/           index of workos-python 10.9.0: 878 classes, 1,980 methods
drift/          docs corpus results + hand sample
eval/           40 questions, hand labels, scores, scripts
tests/          32 tests, synthetic SDK fixtures
```

MIT license. Not affiliated with WorkOS.
