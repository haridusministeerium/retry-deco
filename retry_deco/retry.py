import asyncio
import logging
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from enum import IntFlag
from functools import partial, wraps
from inspect import iscoroutinefunction
from typing import Any

logger = logging.getLogger(__name__)


class OnErrOpts(IntFlag):
    RUN_ON_LAST_TRY = 1
    BREAK_OUT = 2
    # NEXT_OPT = 4


DEFAULT_ONEX_OPTS = OnErrOpts(0)

E = type[BaseException]
C = Callable[..., Any | Awaitable[Any]]
N = int | float  # number
X = Callable[[BaseException], Any]
OnEx = dict[E, C | tuple[C, OnErrOpts]]


def get_fn_name(f: C) -> str:
    if isinstance(f, partial):
        return get_fn_name(f.func)
    return getattr(f, "__name__", f.__class__.__name__)  # from https://github.com/Kludex/starlette/pull/2648


def attempts_exceeded(f: C, count: int):
    logger.error(f"exceeded {count} attempts for {get_fn_name(f)}")


def is_async_callable(f: Callable[..., Any]) -> bool:
    while isinstance(f, partial):
        f = f.func
    # type(f).__call__ rather than f.__call__, so that a class with an async __call__
    # isn't mistaken for an async callable (calling the class constructs an instance).
    return iscoroutinefunction(f) or iscoroutinefunction(type(f).__call__)


def ensure_callable(c: Any, is_async: bool, name: str) -> None:
    if not callable(c):
        raise TypeError(f"{name} must be callable, got {c!r}")
    if is_async_callable(c) != is_async:
        raise TypeError(f"{name} must be {'async' if is_async else 'synchronous'}, got {get_fn_name(c)}")


def validate_params(
    retries: int,
    backoff: N,
    exponential_backoff: bool,
    max_backoff: N,
    jitter: N | tuple[N, N],
    on_exhaustion: bool | X,
):
    if retries < -1:
        raise ValueError("retries must be >= -1 (-1 means retry forever).")

    if exponential_backoff:
        if backoff <= 0:
            raise ValueError("with exponential_backoff backoff must be greater than 0.")
        if max_backoff and max_backoff <= backoff:
            raise ValueError("max_backoff must be greater than backoff.")
    else:
        if backoff < 0:
            raise ValueError("backoff must be >= 0.")
        if max_backoff:
            raise ValueError("max_backoff does not make sense without exponential_backoff.")

    if jitter:
        if isinstance(jitter, tuple):
            if len(jitter) != 2:
                raise ValueError("jitter, when defined as a tuple, must be a range of length 2.")
            j = max(abs(jitter[0]), abs(jitter[1]))
        else:
            j = abs(jitter)
        if j > backoff:
            raise ValueError("jitter extreme must be <= backoff.")

    if not isinstance(on_exhaustion, bool):
        ensure_callable(on_exhaustion, False, "on_exhaustion")


def sanitize_on_exception(onex: None | OnEx | tuple[C, OnErrOpts] | C, is_async: bool) -> OnEx:
    def check_tuple(t):
        if len(t) != 2:
            raise ValueError("on_exception tuple must be of length 2: (callable, OnErrOpts).")
        if not isinstance(t[1], OnErrOpts):
            raise TypeError("second item in on_exception tuple must be OnErrOpts.")
        ensure_callable(t[0], is_async, "on_exception callback")

    if onex is None:
        return {}
    elif isinstance(onex, dict):
        for c in onex.values():
            if isinstance(c, tuple):
                check_tuple(c)
            else:
                ensure_callable(c, is_async, "on_exception callback")
        return dict(onex)  # copy, so later mutation of caller's dict doesn't affect us
    elif isinstance(onex, tuple):
        check_tuple(onex)
        return {Exception: onex}
    else:
        ensure_callable(onex, is_async, "on_exception callback")
        return {Exception: onex}


def handle_delay(
    exception: BaseException,
    count: int,
    retries: int,
    attempts: int,
    on_exhaustion: bool | X,
    backoff: N,
    exponential_backoff: bool,
    max_backoff: N,
    jitter: N | tuple[N, N],
    function: C,
) -> tuple[int, float, Any]:
    count += 1
    logger.warning(f"{count}. attempt: caught error in [{get_fn_name(function)}]: {repr(exception)}")

    if retries != -1 and count >= attempts:
        if on_exhaustion:
            if on_exhaustion is True:
                return count, 0, exception
            return count, 0, on_exhaustion(exception)
        raise exception

    current_backoff: float = backoff
    if exponential_backoff:
        current_backoff *= 2 ** (count - 1)

    if jitter:
        if isinstance(jitter, tuple):
            current_backoff += random.uniform(*jitter)
        else:
            # deviation = jitter * random.random() * random.choice((-1, 1))
            # deviation = jitter * (-1 + 2 * random.random())
            deviation = jitter * random.uniform(-1, 1)
            current_backoff += deviation
    if max_backoff:
        current_backoff = min(current_backoff, max_backoff)

    return count, current_backoff, None


def unpack_callback(cb: tuple[C, OnErrOpts] | C) -> tuple[C, OnErrOpts]:
    opts: OnErrOpts = DEFAULT_ONEX_OPTS
    if isinstance(cb, tuple):
        cb, opts = cb
    return cb, opts


def should_skip_cb(opts: OnErrOpts, last_try: bool) -> bool:
    return last_try and not bool(opts & OnErrOpts.RUN_ON_LAST_TRY)


def retry_logic(
    f: Callable[..., Any],
    expected_exception: E | tuple[E, ...],
    retries: int,
    backoff: N,
    exponential_backoff: bool,
    on_exhaustion: bool | X,
    jitter: N | tuple[N, N],
    max_backoff: N,
    onex: OnEx,
) -> Any:
    count = 0
    attempts = retries + 1
    while retries == -1 or count < attempts:
        try:
            return f()
        except expected_exception as e:
            # check if this exception is something the caller wants special handling for
            for error_type in onex:
                if isinstance(e, error_type):
                    cb, opts = unpack_callback(onex[error_type])
                    if not should_skip_cb(opts, count == retries):
                        cb()
                    if opts & OnErrOpts.BREAK_OUT:
                        break

            count, current_backoff, return_val = handle_delay(
                e,
                count,
                retries,
                attempts,
                on_exhaustion,
                backoff,
                exponential_backoff,
                max_backoff,
                jitter,
                f,
            )
            if current_backoff:
                time.sleep(current_backoff)
    attempts_exceeded(f, count)
    return return_val


async def retry_logic_async(
    f: Callable[..., Awaitable[Any]],
    expected_exception: E | tuple[E, ...],
    retries: int,
    backoff: N,
    exponential_backoff: bool,
    on_exhaustion: bool | X,
    jitter: N | tuple[N, N],
    max_backoff: N,
    onex: OnEx,
) -> Any:
    count = 0
    attempts = retries + 1
    while retries == -1 or count < attempts:
        try:
            return await f()
        except expected_exception as e:
            # check if this exception is something the caller wants special handling for
            for error_type in onex:
                if isinstance(e, error_type):
                    cb, opts = unpack_callback(onex[error_type])
                    if not should_skip_cb(opts, count == retries):
                        await cb()
                    if opts & OnErrOpts.BREAK_OUT:
                        break

            count, current_backoff, return_val = handle_delay(
                e,
                count,
                retries,
                attempts,
                on_exhaustion,
                backoff,
                exponential_backoff,
                max_backoff,
                jitter,
                f,
            )
            if current_backoff:
                await asyncio.sleep(current_backoff)
    attempts_exceeded(f, count)
    return return_val


def retry(
    expected_exception: E | tuple[E, ...] = Exception,
    *,
    retries: int = 1,
    backoff: N = 0,
    exponential_backoff: bool = False,
    on_exhaustion: bool | X = False,
    jitter: N | tuple[N, N] = 0,
    max_backoff: N = 0,
    on_exception: None | OnEx | tuple[C, OnErrOpts] | C = None,
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
                        multiple exception types was given. Applies whenever the
                        exception type matches, even if the callback itself is skipped
                        on the last try for lack of RUN_ON_LAST_TRY
            Be aware if the decorated function is synchronous, on_exception function(s)
            must be synchronous as well and vice versa: for async function they need
            to be asynchronous. default: None
    """

    validate_params(retries, backoff, exponential_backoff, max_backoff, jitter, on_exhaustion)

    def decorator(f: C) -> C:
        if not callable(f):
            raise TypeError(f"decorated object must be callable, got {f!r}")
        is_async = is_async_callable(f)

        onex: OnEx = sanitize_on_exception(on_exception, is_async)

        @wraps(f)
        def wrapper(*args, **kwargs) -> Any:
            return retry_logic(
                partial(f, *args, **kwargs),
                expected_exception,
                retries,
                backoff,
                exponential_backoff,
                on_exhaustion,
                jitter,
                max_backoff,
                onex,
            )

        @wraps(f)
        async def async_wrapper(*args, **kwargs) -> Any:
            return await retry_logic_async(
                partial(f, *args, **kwargs),
                expected_exception,
                retries,
                backoff,
                exponential_backoff,
                on_exhaustion,
                jitter,
                max_backoff,
                onex,
            )

        return async_wrapper if is_async else wrapper

    return decorator


class BaseRetry(ABC):
    """
    Class supporting a more programmatic approach, i.e. w/o a decorator, for retrying logic.
    """

    __slots__ = [
        "expected_exception",
        "retries",
        "backoff",
        "exponential_backoff",
        "on_exhaustion",
        "jitter",
        "max_backoff",
        "on_exception",
    ]

    def __init__(
        self,
        expected_exception: E | tuple[E, ...],
        retries: int,
        backoff: N,
        exponential_backoff: bool,
        on_exhaustion: bool | X,
        jitter: N | tuple[N, N],
        max_backoff: N,
        on_exception: OnEx,
    ):
        validate_params(retries, backoff, exponential_backoff, max_backoff, jitter, on_exhaustion)

        self.expected_exception = expected_exception
        self.retries = retries
        self.backoff = backoff
        self.exponential_backoff = exponential_backoff
        self.on_exhaustion = on_exhaustion
        self.jitter = jitter
        self.max_backoff = max_backoff
        self.on_exception = on_exception
        super().__init__()

    @abstractmethod
    def __call__(self, f: C, *args, **kwargs) -> Any:
        pass


class Retry(BaseRetry):
    """
    Class supporting a more programmatic approach, i.e. w/o a decorator, for retrying logic.
    """

    __slots__ = [
        "expected_exception",
        "retries",
        "backoff",
        "exponential_backoff",
        "on_exhaustion",
        "jitter",
        "max_backoff",
        "on_exception",
    ]

    def __init__(
        self,
        expected_exception: E | tuple[E, ...] = Exception,
        *,
        retries: int = 1,
        backoff: N = 0,
        exponential_backoff: bool = False,
        on_exhaustion: bool | X = False,
        jitter: N | tuple[N, N] = 0,
        max_backoff: N = 0,
        on_exception: None | OnEx | tuple[C, OnErrOpts] | Callable[..., Any] = None,
    ):
        super().__init__(
            expected_exception,
            retries,
            backoff,
            exponential_backoff,
            on_exhaustion,
            jitter,
            max_backoff,
            sanitize_on_exception(on_exception, False),
        )

    def __call__(self, f: Callable[..., Any], *args, **kwargs) -> Any:
        ensure_callable(f, False, "function passed to Retry (use RetryAsync for async functions)")
        return retry_logic(
            partial(f, *args, **kwargs),
            self.expected_exception,
            self.retries,
            self.backoff,
            self.exponential_backoff,
            self.on_exhaustion,
            self.jitter,
            self.max_backoff,
            self.on_exception,
        )


class RetryAsync(BaseRetry):
    """
    Class supporting a more programmatic approach, i.e. w/o a decorator, for retrying logic.
    """

    __slots__ = [
        "expected_exception",
        "retries",
        "backoff",
        "exponential_backoff",
        "on_exhaustion",
        "jitter",
        "max_backoff",
        "on_exception",
    ]

    def __init__(
        self,
        expected_exception: E | tuple[E, ...] = Exception,
        *,
        retries: int = 1,
        backoff: N = 0,
        exponential_backoff: bool = False,
        on_exhaustion: bool | X = False,
        jitter: N | tuple[N, N] = 0,
        max_backoff: N = 0,
        on_exception: None | OnEx | tuple[C, OnErrOpts] | Callable[..., Awaitable[Any]] = None,
    ):
        super().__init__(
            expected_exception,
            retries,
            backoff,
            exponential_backoff,
            on_exhaustion,
            jitter,
            max_backoff,
            sanitize_on_exception(on_exception, True),
        )

    async def __call__(self, f: Callable[..., Awaitable[Any]], *args, **kwargs) -> Any:
        ensure_callable(f, True, "function passed to RetryAsync (use Retry for synchronous functions)")
        return await retry_logic_async(
            partial(f, *args, **kwargs),
            self.expected_exception,
            self.retries,
            self.backoff,
            self.exponential_backoff,
            self.on_exhaustion,
            self.jitter,
            self.max_backoff,
            self.on_exception,
        )
