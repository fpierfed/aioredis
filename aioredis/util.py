import asyncio
from functools import lru_cache
import sys

from asyncio.base_events import BaseEventLoop

from .log import logger


PY_35 = sys.version_info >= (3, 5)

_NOTSET = object()


def correct_aiter(func):
    if sys.version_info >= (3, 5, 2):
        return func
    else:
        return asyncio.coroutine(func)


# NOTE: never put here anything else;
#       just this basic types
_converters = {
    bytes: lambda val: val,
    bytearray: lambda val: val,
    str: lambda val: val.encode('utf-8'),
    int: lambda val: str(val).encode('utf-8'),
    float: lambda val: str(val).encode('utf-8'),
    }


@lru_cache(maxsize=1024)
def _bytes_len(nsized):
    return str(nsized).encode('utf-8')


def encode_command(*args):
    """Encodes arguments into redis bulk-strings array.

    Raises TypeError if any of args not of bytes, str, int or float type.
    """
    parts = [b'*', _bytes_len(len(args)), b'\r\n']
    for arg in args:
        try:
            barg = _converters[type(arg)](arg)
            parts += [b'$', _bytes_len(len(barg)), b'\r\n', barg, b'\r\n']
        except:
            raise TypeError("Argument {!r} expected to be of bytes,"
                            " str, int or float type".format(arg))
    return bytearray(b''.join(parts))


def decode(obj, encoding):
    if isinstance(obj, bytes):
        return obj.decode(encoding)
    elif isinstance(obj, list):
        return [decode(o, encoding) for o in obj]
    return obj


@asyncio.coroutine
def wait_ok(fut):
    res = yield from fut
    if res in (b'QUEUED', 'QUEUED'):
        return res
    return res in (b'OK', 'OK')


@asyncio.coroutine
def wait_convert(fut, type_, **kwargs):
    result = yield from fut
    if result in (b'QUEUED', 'QUEUED'):
        return result
    return type_(result, **kwargs)


@asyncio.coroutine
def wait_make_dict(fut):
    res = yield from fut
    if res in (b'QUEUED', 'QUEUED'):
        return res
    it = iter(res)
    return dict(zip(it, it))


class coerced_keys_dict(dict):

    def __getitem__(self, other):
        if not isinstance(other, bytes):
            other = _converters[type(other)](other)
        return dict.__getitem__(self, other)

    def __contains__(self, other):
        if not isinstance(other, bytes):
            other = _converters[type(other)](other)
        return dict.__contains__(self, other)


if PY_35:
    class _BaseScanIter:
        __slots__ = ('_scan', '_cur', '_ret')

        def __init__(self, scan):
            self._scan = scan
            self._cur = b'0'
            self._ret = []

        @correct_aiter
        def __aiter__(self):
            return self

    class _ScanIter(_BaseScanIter):

        @asyncio.coroutine
        def __anext__(self):
            while not self._ret and self._cur:
                self._cur, self._ret = yield from self._scan(self._cur)
            if not self._cur and not self._ret:
                raise StopAsyncIteration  # noqa
            else:
                ret = self._ret.pop(0)
                return ret

    class _ScanIterPairs(_BaseScanIter):

        @asyncio.coroutine
        def __anext__(self):
            while not self._ret and self._cur:
                self._cur, ret = yield from self._scan(self._cur)
                self._ret = list(zip(ret[::2], ret[1::2]))
            if not self._cur and not self._ret:
                raise StopAsyncIteration  # noqa
            else:
                ret = self._ret.pop(0)
                return ret


def _set_result(fut, result):
    if fut.done():
        logger.debug("Waiter future is already done %r", fut)
        assert fut.cancelled(), (
            "waiting future is in wrong state", fut, result)
    else:
        fut.set_result(result)


def _set_exception(fut, exception):
    if fut.done():
        logger.debug("Waiter future is already done %r", fut)
        assert fut.cancelled(), (
            "waiting future is in wrong state", fut, exception)
    else:
        fut.set_exception(exception)


if hasattr(asyncio, 'ensure_future'):
    async_task = asyncio.ensure_future
else:
    async_task = asyncio.async  # Deprecated since 3.4.4


# create_future is new in version 3.5.2
if hasattr(BaseEventLoop, 'create_future'):
    def create_future(loop):
        return loop.create_future()
else:
    def create_future(loop):
        return asyncio.Future(loop=loop)
