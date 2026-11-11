[![PyPI version](https://badge.fury.io/py/retry-deco.svg)](https://badge.fury.io/py/retry-deco)
    
# Retry decorator

Tool for retrying tasks on failure. Optionally a callback can be invoked
between tries. Supports both synchronous & async.

## Installation

```sh
pip install retry-deco
```

## Features

- async support
- allows executing callback between attempts
- when all tries are exhausted, then either
  - last caught exception is re-raised (default); or
  - last caught exception is returned; or
  - optional callback is invoked and its result is returned
- customizable backoff

## API

```python
def retry(
    expected_exception: type[E] | tuple[type[E], ...] = Exception,
    *,
    retries: int = 1,
    backoff: N = 0,
    exponential_backoff: bool = False,
    on_exhaustion: bool|X = False,
    jitter: N | tuple[N, N] = 0,
    max_backoff: N = 0,
    on_exception: None | dict | tuple[C, OnErrOpts] | C = None,
):
    """Retry decorator for synchronous and asynchronous functions.

    Arguments:
        expected_exception:
            exception or tuple of exceptions to catch. default: Exception

    Keyword arguments:
        retries:
            how much times the function will be retried, -1 for infinite. default: 1
            note total attempts will be retries + 1
        backoff:
            time interval between the attempts. default: 0
        exponential_backoff:
            current_backoff = backoff * 2 ** (n - 1), where n is the number of failed
            attempts so far, i.e. backoff, 2*backoff, 4*backoff, ... default: False
        on_exhaustion:
            - False if exception should be re-raised when all attempts fail (default).
            - True if raised exception should be returned, not re-raised.
            - if callable, then on attempt exhaustion it'll be invoked with the
              causing exception, and its return value will be returned. 
              This callable must always be synchronous.
        jitter:
            maximum value of deviation from the current_backoff.
            - if a number, then jitter will be in the range (-value, value)
            - if a (min, max) tuple then it defines the range to generate jitter from.
            default: 0
        max_backoff:
            current_backoff = min(current_backoff, max_backoff).
            disabled on 0. default: 0
        on_exception:
            defines callback(s) that should be invoked on failed attempts. Types can be:
            - dict for exception type to callable|(callable, opt) mappings
            - callable
            - (callable, opts) tuple
            The options modify the callback behavior:
            - RUN_ON_LAST_TRY to invoke callback even if there are no attempts remaining
            - BREAK_OUT to stop processing remaining callbacks when dict with
                        multiple exception types was given
            Be aware if the decorated function is synchronous, on_exception function(s)
            must be synchronous as well and vice versa: for async function they need
            to be asynchronous. default: None
    """
```

## Examples

### decorator

```python

from retry_deco import retry, OnErrOpts
```

```python
@retry(retries=-1)
def make_trouble():
	'''Retry until success, no sleep between attempts'''
```

```python
@retry(ZeroDivisionError, retries=3, backoff=2)
def make_trouble():
	'''Retry on ZeroDivisionError, raise error after 4 attempts,
       sleep 2 seconds between attempts.'''
```

```python
@retry((ValueError, TypeError), backoff=1, exponential_backoff=True)
def make_trouble():
	'''Retry on ValueError or TypeError, sleep 1, 2, 4, 8, ... seconds between attempts.'''
```

```python
@retry((ValueError, TypeError), backoff=3, exponential_backoff=True, max_backoff=1000)
def make_trouble():
	'''Retry on ValueError or TypeError, sleep 3, 6, 12, 24, ..., 384, 768, 1000, 1000 ... seconds between attempts.'''
```

```python
@retry(Exception, on_exhaustion=True)
def make_trouble():
	'''Retry on all Exceptions, retry only once. If no success, then causing
       exception is returned'''
```

```python
@retry(Exception, on_exhaustion=lambda ex: 12)
def make_trouble():
	'''Retry on all Exceptions, retry only once. If no success, then 12 is returned'''
```

```python
@retry(Exception, on_exception=lambda: do_something_between_tries())
def make_trouble():
	'''Retry on all Exceptions, retry only once. Between attempts
       do_something_between_tries() is invoked'''
```

```python
@retry(Exception,
       on_exception={
           TypeError: lambda: print("called if TypeError was thrown"),
           Exception: lambda: print("called if Exception was thrown")
       })
def make_trouble():
	'''Retry on all Exceptions, retry only once. Between attempts a callback is/are
       invoked, depending on type of caught exceptions.
```

```python
@retry(Exception,
       on_exception={
           TypeError: (lambda: print("called if TypeError was thrown"), OnErrOpts.BREAK_OUT),
           Exception: lambda: print("called if Exception was thrown")
       })
def make_trouble():
	'''Same as above, but if caught exception is instance of TypeError, then
       Exception's callback doesn't get invoked due to TypeError callback
       having OnErrOpts.BREAK_OUT option bit set.
```

```python
@retry(Exception,
       on_exception={
           TypeError: (lambda: print("called if TypeError was thrown"), OnErrOpts.RUN_ON_LAST_TRY),
           Exception: lambda: print("called if Exception was thrown")
       })
def make_trouble():
	'''Similar to above, but this time the set option is OnErrOpts.RUN_ON_LAST_TRY.
       This means TypeError callback will also be invoked on the very last
       attempt failure, whereas Exception's callback won't.
```

```python
@retry(Exception,
       on_exception={
           TypeError: (lambda: print("called if TypeError was thrown"), OnErrOpts.RUN_ON_LAST_TRY | OnErrOpts.BREAK_OUT),
           Exception: lambda: print("called if Exception was thrown")
       })
def make_trouble():
	'''Similar to above, but this time TypeError callback has both options set.'''
```

### instance

Similar to decorator, but allows for more programmatic usage.

```python
from retry_deco import Retry


def make_trouble():
    raise RuntimeError()

retry = Retry(retries=-1, backoff=1)
result = retry(make_trouble)

# retry instances can be reused:
result = retry(some_other_function)

# ...or invoked directly:
result = Retry(retries=2, backoff=2)(make_trouble)
```

Async instance:

```python
import asyncio
from retry_deco import RetryAsync


async def make_trouble():
    raise RuntimeError()

async def main():
    retry = RetryAsync(retries=2, backoff=2)
    result = await retry(make_trouble)
    result = await retry(some_other_async_function)

asyncio.run(main())
```

Feel free to run the `examples.py` from the repo root.

## Credits

This project is largely influenced & sourced from the projects listed below

## Prior art

- [gitlab/ramil.minnigaliev/the-retry](https://gitlab.com/ramil.minnigaliev/the-retry)
- [Abeautifulsnow/PyRetry](https://github.com/Abeautifulsnow/PyRetry)
- [adityaprakash-bobby/retry_module](https://github.com/adityaprakash-bobby/retry_module)
- [eSAMTrade/retry](https://github.com/eSAMTrade/retry)
