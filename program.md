# autoresearch

This repository is set up for short, repeated training experiments where the only moving part is `train.py`. The general goal is to lower validation bits-per-byte (`val_bpb`) under a fixed five-minute training budget while keeping VRAM usage within a reasonable range.

## How a Run Is Usually Set Up

Before running experiments, it is worth reading the small set of in-scope files end to end:

- `README.md` for repository context
- `prepare.py` for data preparation, tokenization, dataloading, and evaluation behavior
- `modal_train.py` for the Modal wrapper that runs training remotely on an A100 and uses a Modal volume for cached assets
- `train.py` for the model, optimizer, and training loop

The Modal volume `autoresearch-cache` is expected to contain both `data/` and `tokenizer/`. If those assets are missing, the preparation entrypoint needs to be run once before experimentation:

```bash
modal run modal_train.py::prepare_data
```

The run directory is also expected to have an untracked `results.tsv` with this header:

```tsv
commit	val_bpb	memory_gb	status	description
```

The first recorded experiment should be the untouched baseline.

## Experiment Constraints

Each experiment runs on a single GPU through:

```bash
modal run modal_train.py
```

The timed training budget is fixed at five minutes of wall-clock training time, excluding startup and compilation overhead.

Only `train.py` is intended to change during experimentation. Model architecture, optimizer settings, hyperparameters, batch size, and training-loop details are all fair game there.

The following are treated as fixed:

- `prepare.py`, which defines the evaluation harness, tokenizer behavior, dataloading, and fixed constants
- `modal_train.py`, which is infrastructure for remote execution
- dependencies outside what is already present in `pyproject.toml`

The primary objective is simple: lower `val_bpb`.

VRAM is a soft constraint rather than a hard one. More memory is acceptable if it buys a meaningful metric improvement, but gratuitous blowups are not desirable.

There is also a simplicity bias. When two changes land in roughly the same place on the metric, the simpler one is better. A tiny gain that adds brittle complexity is usually not worth keeping. A tiny gain that comes from deleting code or simplifying the design usually is.

## Expected Output

At the end of a successful run, training prints a summary like:

```text
---
val_bpb:          0.997900
training_seconds: 300.1
total_seconds:    325.9
peak_vram_mb:     45060.2
mfu_percent:      39.80
total_tokens_M:   499.6
num_steps:        953
num_params_M:     50.3
depth:            8
```

In the happy path, the key metric can be pulled from `run.log` with:

```bash
grep "^val_bpb:" run.log
```

## Recording Results

Every completed experiment is meant to append one row to `results.tsv`. The columns are:

1. short git commit hash
2. `val_bpb`
3. peak memory in GB, rounded to one decimal place from `peak_vram_mb / 1024`
4. `keep`, `discard`, or `crash`
5. a short plain-language description of what the experiment changed

For crashes, the convention is `0.000000` for `val_bpb` and `0.0` for memory.

Example:

```tsv
commit	val_bpb	memory_gb	status	description
a1b2c3d	0.997900	44.0	keep	baseline
b2c3d4e	0.993200	44.2	keep	increase LR to 0.04
c3d4e5f	1.005000	44.0	discard	switch to GeLU activation
d4e5f6g	0.000000	0.0	crash	double model width (OOM)
```

`results.tsv` is intentionally local bookkeeping and should stay untracked.

## Operational Expectations

These runs are expected to take about five minutes of training time, plus startup and evaluation overhead. If a run exceeds roughly ten minutes of wall-clock time without producing a usable result, it should be treated as a failed attempt.

Crash handling is meant to be pragmatic. Easy mistakes such as typos or similarly obvious bugs are worth fixing and rerunning. Ideas that are fundamentally broken, repeatedly unstable, or obviously too expensive can simply be logged as crashes and skipped.

The broader design assumption is that experimentation may continue autonomously for long stretches once the initial setup is in place. The repository is meant to support a long-running search process where many small ideas are tried, measured, and either kept or discarded.