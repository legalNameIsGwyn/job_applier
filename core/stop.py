"""A shared "please stop" flag for long loops.

main.py sets it when you press Ctrl-C; loops that can stop early check it, and
their waits use wait() so they wake up at once instead of sleeping it out.
"""

import signal
import threading
from contextlib import contextmanager

_STOP = threading.Event()


def request_stop() -> None:
    """Ask the running loop to stop at the next safe point."""
    _STOP.set()


def stop_requested() -> bool:
    return _STOP.is_set()


def reset() -> None:
    """Clear the flag (done after a stopped stage has been handled)."""
    _STOP.clear()


def wait(seconds: float) -> bool:
    """Sleep up to `seconds`, waking at once if a stop is requested. True means: stop now."""
    return _STOP.wait(seconds)


def enable_soft_stop():
    """Make Ctrl-C ask running loops to stop instead of raising KeyboardInterrupt.

    Returns a function that puts the normal Ctrl-C back. A second Ctrl-C does nothing more.
    Only works in the main thread; elsewhere it changes nothing.
    """
    if threading.current_thread() is not threading.main_thread():
        return lambda: None

    def on_ctrl_c(signum, frame):
        if not _STOP.is_set():
            from core.console import decision
            print()
            decision("warn", "stopping: finishing the current request, then moving on")
        request_stop()

    previous = signal.signal(signal.SIGINT, on_ctrl_c)
    return lambda: signal.signal(signal.SIGINT, previous)


@contextmanager
def soft_stop():
    """enable_soft_stop() as a with-block: the normal Ctrl-C is put back when the block ends."""
    restore = enable_soft_stop()
    try:
        yield
    finally:
        restore()