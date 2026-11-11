## 0.0.6 (unreleased)
---------------------

- breaking: argument validation raises ValueError/TypeError instead of AssertionError
  (validation is no longer stripped under `python -O`)
- breaking: `Retry` rejects async functions and `RetryAsync` rejects synchronous ones
  with TypeError, instead of silently not retrying
- breaking: `retries` below -1 raises ValueError (previously UnboundLocalError on call)
- fix: async `on_exhaustion` is now rejected by `Retry`/`RetryAsync` as well, not only by `retry`
- fix: `X` (on_exhaustion type) now takes the exception instance, not the exception class
- fix: objects with an async `__call__` are now detected as async
- fix: `on_exception` dict is copied, so mutating it afterwards no longer affects retry behavior
- docs: correct exponential backoff formula and examples


## 0.0.5 (2025-11-21)
---------------------

- update typing: on_exception now typed to OnEx
- expected_exception now defaults to Exception, was BaseException


## 0.0.4 (2025-11-18)
---------------------

- maximum_backoff -> max_backoff
- on_exception no longer may be a list - only tuple is allowed as an iterable
- add documentation/readme
- add examples.py


## 0.0.3 (2025-11-17)
- add async support
