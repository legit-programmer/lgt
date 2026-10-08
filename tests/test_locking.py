import pytest

from lgt.locking import RuntimeLock


def test_only_one_runtime_can_own_a_database_directory(tmp_path):
    first = RuntimeLock(tmp_path / "workspace.lock")
    second = RuntimeLock(tmp_path / "workspace.lock")
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="another backend"):
            second.acquire()
    finally:
        first.close()
    second.acquire()
    second.close()
