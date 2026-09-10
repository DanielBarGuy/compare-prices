"""Inter-process lock shared by catalog and image database writers."""
import fcntl
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def database_lock(data_dir):
    """Serialize writers that replace or update the local SQLite catalog."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / ".database.lock"
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
