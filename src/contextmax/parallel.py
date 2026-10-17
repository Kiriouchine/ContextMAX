"""Work spread over this PC's processors, with the same result as one piece at a time.

A piece of work (one document to read, one scan to recognise) depends on its own input only. It runs in a
process of its own: Python runs one thread at a time in a process, and the PDF library is not made for
threads. A worker writes only its own document's files, named by the document's key, which no other
document shares; the main process writes every file the documents share (the index, the lists), in the
same sorted order as ever. So the index is the same, byte for byte, with one worker or with twelve, and
one worker (CONTEXTMAX_WORKERS=1) is the way ContextMAX always ran: no extra process at all.

How many: one per processor thread but one (left for Windows and the window), as many as the memory has
room for (about MEMORY_PER_WORKER_GB each), never more than MAX_WORKERS. Workers run below normal
priority, so the PC stays quick to use while a build runs. Word and Excel are never driven from a
worker: they open one document at a time, in the main process.

A worker that dies (not an error in the document: the process itself) takes its pool with it. The
pieces still out are then done again one at a time, each in a process of its own, up to three times:
the piece that kills its process every time is named as unreadable, with that reason, and every other
piece still gets its result.
"""
from __future__ import annotations

import concurrent.futures as cf
import multiprocessing
import os
import sys
from concurrent.futures.process import BrokenProcessPool

from contextmax import util

MEMORY_PER_WORKER_GB = 1.0
MAX_WORKERS = 16
RETRIES = 3                    # a piece whose process dies is done again, alone, this many times


def memory_gb() -> float:
    """The memory free now, in GB (8 when it cannot be told)."""
    if os.name == "nt":
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        s = Status()
        s.dwLength = ctypes.sizeof(Status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):
            return s.ullAvailPhys / 2 ** 30
        return 8.0
    try:
        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 2 ** 30
    except (ValueError, OSError, AttributeError):
        return 8.0


def workers() -> int:
    """How many pieces of work run at once: CONTEXTMAX_WORKERS when it is set, else as this PC allows."""
    asked = os.environ.get("CONTEXTMAX_WORKERS", "").strip()
    if asked.isdigit() and int(asked) >= 1:
        return int(asked)
    cpus = os.cpu_count() or 1
    return max(1, min(cpus - 1, int(memory_gb() / MEMORY_PER_WORKER_GB), MAX_WORKERS))


def in_worker() -> bool:
    return os.environ.get("CONTEXTMAX_WORKER") == "1"


def threads_per_worker() -> int:
    """Threads a worker's own number crunching may use (text recognition): the processors shared out."""
    try:
        return max(1, int(os.environ.get("CONTEXTMAX_WORKER_THREADS") or 1))
    except ValueError:
        return 1


_SHARED: list = [None]


def shared():
    """What every piece of work of the running spread reads (tables too large to send with each piece)."""
    return _SHARED[0]


def _start(threads: int, data=None) -> None:
    """A new worker: it says nothing (the build's own lines are the main process's), is never asked to
    stop (the main process stops it), and gives way to what the person at the PC is doing."""
    _SHARED[0] = data
    os.environ["CONTEXTMAX_WORKER"] = "1"
    os.environ["CONTEXTMAX_WORKER_THREADS"] = str(threads)
    for name in ("CONTEXTMAX_LIVE", "CONTEXTMAX_STOP_FILE"):
        os.environ.pop(name, None)
    sys.stdout = sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115 - lives as long as the worker
    if os.name == "nt":
        import ctypes

        below_normal = 0x4000
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), below_normal)


class Crashed(Exception):
    """The process doing this piece of work stopped."""


class Spread:
    """`fn` over `items`, `n` at a time (by default as many as this PC allows). The results come as they
    are ready: (index of the item, result), where the result is the exception when `fn` raised one.
    With one at a time, `fn` runs here, item by item, in order. Fewer items than `min_items` are done
    here too: starting the workers would take longer than the work. `data` is what shared() gives."""

    def __init__(self, fn, items, n: int | None = None, data=None, min_items: int = 2):
        self.fn, self.items, self.data = fn, list(items), data
        self.n = max(1, min(workers() if n is None else n, len(self.items)))
        if len(self.items) < min_items:
            self.n = 1
        self.pool, self.futures = None, {}
        if self.n > 1:
            threads = max(1, (os.cpu_count() or 1) // self.n)
            self.pool = self._pool(self.n, threads, data)
            self.futures = {self.pool.submit(fn, item): i for i, item in enumerate(self.items)}

    @staticmethod
    def _pool(n: int, threads: int, data=None) -> cf.ProcessPoolExecutor:
        return cf.ProcessPoolExecutor(n, mp_context=multiprocessing.get_context("spawn"), initializer=_start,
                                      initargs=(threads, data))

    def results(self):
        if self.pool is None and not self.futures:
            before, _SHARED[0] = _SHARED[0], self.data
            try:
                for i, item in enumerate(self.items):
                    util.check_stop()
                    try:
                        result = self.fn(item)
                    except util.Stopped:
                        raise
                    except Exception as exc:  # noqa: BLE001 - the piece's failure is its result
                        result = exc
                    yield i, result
            finally:
                _SHARED[0] = before
            return
        pending, broken = set(self.futures), []
        while pending:
            util.check_stop()
            done, pending = cf.wait(pending, timeout=0.5, return_when=cf.FIRST_COMPLETED)
            for f in sorted(done, key=lambda f: self.futures[f]):
                i = self.futures[f]
                try:
                    yield i, f.result()
                except BrokenProcessPool:
                    broken.append(i)
                except Exception as exc:  # noqa: BLE001 - the piece's failure is its result
                    yield i, exc
        if broken:
            self.stop()
            for i in sorted(broken):
                util.check_stop()
                yield i, self._alone(self.items[i])

    def _alone(self, item):
        return isolated(self.fn, item, self.data)

    def stop(self) -> None:
        """Every worker ended now, finished or not: on a stop, on an error, at the end."""
        pool, self.pool = self.pool, None
        if pool is None:
            return
        processes = list((getattr(pool, "_processes", None) or {}).values())
        pool.shutdown(wait=False, cancel_futures=True)
        for p in processes:
            try:
                p.terminate()
            except (OSError, AttributeError, ValueError):
                pass
        for p in processes:
            try:
                p.join(5)
            except (OSError, AttributeError, ValueError, AssertionError):
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()


def isolated(fn, item, data=None):
    """`fn(item)` in a process of its own, done again up to RETRIES times when that process dies: the result,
    the exception it raised, or Crashed."""
    for _ in range(RETRIES):
        util.check_stop()
        one = Spread._pool(1, os.cpu_count() or 1, data)
        try:
            return one.submit(fn, item).result()
        except BrokenProcessPool:
            continue
        except Exception as exc:  # noqa: BLE001
            return exc
        finally:
            one.shutdown(wait=True, cancel_futures=True)
    return Crashed(f"the process reading it stopped, {RETRIES} times over (the file may be damaged)")

def _part(job):
    fn, items = job
    return [fn(x) for x in items]


def map_in_order(fn, items, data=None, min_items: int = 200, progress=None) -> list:
    """`fn` of every item, in the items' order, the items handed out in parts of a few dozen. Meant for a
    stage's own computation, where an error is a fault of ContextMAX: the first one is raised, as it
    would be one at a time. `progress` (util.Progress) counts the items done."""
    items = list(items)
    n = workers() if len(items) >= min_items else 1
    if n <= 1:
        out = []
        with Spread(fn, items, 1, data=data) as spread:
            for _, result in spread.results():
                if isinstance(result, BaseException):
                    raise result
                out.append(result)
                if progress:
                    progress.tick()
        return out
    size = max(1, -(-len(items) // (n * 4)))
    parts = [items[i:i + size] for i in range(0, len(items), size)]
    done: list = [None] * len(parts)
    with Spread(_part, [(fn, part) for part in parts], n, data=data) as spread:
        for i, result in spread.results():
            if isinstance(result, BaseException):
                raise result
            done[i] = result
            if progress:
                progress.tick(n=len(parts[i]))
    return [x for part in done for x in part]
