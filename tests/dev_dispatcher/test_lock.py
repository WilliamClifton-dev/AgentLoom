from pathlib import Path

import pytest

from agentloom.dev_dispatcher.lock import DispatcherLock


def test_lock_prevents_concurrent_dispatchers(tmp_path: Path) -> None:
    path = tmp_path / "dispatcher.lock"
    with DispatcherLock(path):
        with pytest.raises(RuntimeError, match="already running"):
            with DispatcherLock(path):
                pass
    assert not path.exists()


def test_lock_replaces_stale_process_lock(tmp_path: Path) -> None:
    path = tmp_path / "dispatcher.lock"
    path.write_text("999999999", encoding="ascii")
    with DispatcherLock(path):
        assert path.exists()
    assert not path.exists()
