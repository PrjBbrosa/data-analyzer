"""A slow manager operation must not occupy its caller/event thread."""
import threading

from tools.extension_manager.worker import BackgroundOperation


def test_slow_operation_returns_control_and_delivers_result():
    entered, release = threading.Event(), threading.Event()
    caller = threading.get_ident()
    worker = BackgroundOperation()
    def operation():
        assert threading.get_ident() != caller
        entered.set()
        assert release.wait(2)
        return 'done'
    worker.start(operation)
    assert entered.wait(1)
    assert worker.poll() is None
    release.set()
    worker.thread.join(2)
    assert worker.poll() == ('result', 'done')


def test_errors_are_delivered_and_parallel_mutations_rejected():
    import pytest
    hold = threading.Event()
    worker = BackgroundOperation()
    worker.start(lambda: hold.wait(2))
    try:
        with pytest.raises(RuntimeError):
            worker.start(lambda: None)
    finally:
        hold.set()
        worker.thread.join(2)
        worker.poll()
    def broken():
        raise ValueError('programming error')
    worker.start(broken)
    worker.thread.join(2)
    kind, error = worker.poll()
    assert kind == 'error'
    assert isinstance(error, ValueError)
