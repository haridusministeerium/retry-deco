# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`retry-deco`: a dependency-free retry decorator/instance library for sync and async callables (Python >=3.11). All library code lives in `retry_deco/retry.py`; `retry_deco/__init__.py` re-exports the public API (including the type aliases `E`, `C`, `N`, `X`, `OnEx`). The public API and its semantics are documented in `README.md` and the `retry()` docstring. Keep both in sync when changing parameters or behavior.

## Commands

The venv is managed by mise (`mise.toml` creates `.venv` via uv).

```sh
pip install -e .[dev]                          # pytest, pytest-asyncio, pytest-cov, ruff, ty
pytest                                          # all tests (config in pytest.ini: coverage, doctests, -vvl)
pytest tests/test_retry.py::test_name           # single test
ruff check . && ruff format .                   # lint/format (line-length 120; rules E,W,F,I,B,UP)
ty check                                        # type checking
python examples.py                              # runnable usage examples
```

pytest config lives in `pytest.ini`, not `pyproject.toml`, because pytest-asyncio still requires pytest <9 (no TOML config support). `asyncio_mode = auto`, so async tests need no marker. `strict = true` is set.

## Architecture

There are three entry points over two shared engines:

- `retry(...)` is the decorator. It picks `wrapper` or `async_wrapper` based on `is_async_callable(f)` at decoration time.
- `Retry` / `RetryAsync` are reusable instances (both subclass `BaseRetry`) that are called as `instance(f, *args, **kwargs)`.
- All three wrap the call in `functools.partial` and delegate to `retry_logic` (sync) or `retry_logic_async`. These two functions are deliberately parallel copies, so any behavior change must be applied to both.

Shared helpers used by both paths:
- `validate_params` / `sanitize_on_exception` / `ensure_callable` validate arguments at construction or decoration time, raising `ValueError` or `TypeError` (never `assert`). Sync-vs-async detection always goes through `is_async_callable`, which handles partials and objects with an async `__call__`. `sanitize_on_exception` normalizes every `on_exception` form (callable, `(callable, OnErrOpts)`, dict) into a `dict[exception_type, cb | (cb, opts)]`, and requires callbacks to match the sync/async nature of the wrapped function.
- `handle_delay` increments the attempt count, decides exhaustion (re-raise, return the exception, or return `on_exhaustion(exc)`; `on_exhaustion` is always sync), and computes the backoff (exponential, then jitter, then `max_backoff` clamp).
- `OnErrOpts` is an `IntFlag` (`RUN_ON_LAST_TRY`, `BREAK_OUT`). On the final attempt, callbacks are skipped unless `RUN_ON_LAST_TRY` is set. `BREAK_OUT` stops iterating the remaining dict entries.

Semantics to keep in mind: `retries=-1` means infinite, and total attempts = `retries + 1`.

## Release / CI

- Versioning and `CHANGELOG.md` are managed by zest.releaser (`[tool.zest-releaser]` in `pyproject.toml`, markdown history format). Add changelog entries under the top `(unreleased)` section.
- Drone (`.drone.yml`) runs `fullrelease` on master, which auto-tags and pushes, and publishes to PyPI on tags. GitHub Actions (`.github/workflows/build-release.yml`) calls a shared org workflow. Note that Drone's test step runs `tox`, but the repo has no tox config.
