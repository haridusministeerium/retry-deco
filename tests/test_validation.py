from functools import partial

import pytest

from retry_deco import OnErrOpts, Retry, RetryAsync, retry


def sync_fail():
    raise RuntimeError()


async def async_fail():
    raise RuntimeError()


async def async_cb(*_):
    pass


def sync_cb(*_):
    pass


class AsyncCallable:
    def __init__(self):
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        raise RuntimeError()


def test_on_exhaustion__receives_exception_instance():
    received = []

    @retry(RuntimeError, on_exhaustion=lambda e: received.append(e) or 1)
    def f():
        raise RuntimeError("boom")

    assert f() == 1
    assert isinstance(received[0], RuntimeError)


def test_retry_instance__rejects_async_function():
    with pytest.raises(TypeError, match="RetryAsync"):
        Retry()(async_fail)


async def test_retry_async_instance__rejects_sync_function():
    with pytest.raises(TypeError, match="Retry "):
        await RetryAsync()(sync_fail)


async def test_retry_async_instance__accepts_partial_of_async_function():
    # partial-wrapped async functions must still be recognized as async
    with pytest.raises(RuntimeError):
        await RetryAsync()(partial(async_fail))


@pytest.mark.parametrize("factory", [Retry, RetryAsync, lambda **kw: retry(**kw)])
def test_on_exhaustion__rejects_async_callable(factory):
    with pytest.raises(TypeError, match="on_exhaustion"):
        factory(on_exhaustion=async_cb)


@pytest.mark.parametrize("factory", [Retry, RetryAsync, lambda **kw: retry(**kw)])
def test_on_exhaustion__rejects_non_callable(factory):
    with pytest.raises(TypeError, match="on_exhaustion"):
        factory(on_exhaustion=42)


@pytest.mark.parametrize("factory", [Retry, RetryAsync, lambda **kw: retry(**kw)])
def test_retries__below_minus_one_rejected(factory):
    with pytest.raises(ValueError, match="retries"):
        factory(retries=-2)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"backoff": -1},
        {"max_backoff": 5},
        {"exponential_backoff": True},
        {"exponential_backoff": True, "backoff": 2, "max_backoff": 1},
        {"backoff": 1, "jitter": 2},
        {"backoff": 1, "jitter": (0, 2)},
        {"backoff": 1, "jitter": (0, 0.5, 1)},
    ],
)
def test_invalid_backoff_params__raise_value_error(kwargs):
    with pytest.raises(ValueError):
        retry(**kwargs)
    with pytest.raises(ValueError):
        Retry(**kwargs)


def test_on_exception__sync_callback_for_async_function_rejected():
    with pytest.raises(TypeError, match="async"):
        retry(on_exception=sync_cb)(async_fail)
    with pytest.raises(TypeError, match="async"):
        RetryAsync(on_exception=sync_cb)


def test_on_exception__async_callback_for_sync_function_rejected():
    with pytest.raises(TypeError, match="synchronous"):
        retry(on_exception={ValueError: async_cb})(sync_fail)
    with pytest.raises(TypeError, match="synchronous"):
        Retry(on_exception=(async_cb, OnErrOpts.BREAK_OUT))


def test_on_exception__invalid_tuple():
    with pytest.raises(TypeError, match="OnErrOpts"):
        Retry(on_exception=(sync_cb, 1))
    with pytest.raises(ValueError, match="length 2"):
        Retry(on_exception=(sync_cb, OnErrOpts.BREAK_OUT, 1))


def test_on_exception__non_callable_rejected():
    with pytest.raises(TypeError, match="callable"):
        Retry(on_exception=42)


def test_on_exception__dict_is_copied():
    calls = []
    onex = {RuntimeError: (lambda: calls.append(1), OnErrOpts.RUN_ON_LAST_TRY)}
    instance = Retry(on_exception=onex)
    onex.clear()

    with pytest.raises(RuntimeError):
        instance(sync_fail)
    assert calls == [1, 1]


def test_decorator__non_callable_rejected():
    with pytest.raises(TypeError, match="callable"):
        retry()(42)


async def test_decorator__async_callable_object_is_retried():
    obj = AsyncCallable()
    with pytest.raises(RuntimeError):
        await retry(retries=2)(obj)()
    assert obj.calls == 3


async def test_retry_async_instance__async_callable_object_is_retried():
    obj = AsyncCallable()
    with pytest.raises(RuntimeError):
        await RetryAsync(retries=2)(obj)
    assert obj.calls == 3


def test_class_with_async_call__is_not_treated_as_async():
    # calling the class itself constructs an instance synchronously
    assert isinstance(Retry()(AsyncCallable), AsyncCallable)
