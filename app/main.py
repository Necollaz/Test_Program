import sys
from pathlib import Path

from app.ui import run_app


def acquire_single_instance_lock() -> object:
    lock_path = Path.home() / ".interview_assistant.lock"
    lock_file = lock_path.open("w", encoding="utf-8")

    if sys.platform == "win32":
        import msvcrt

        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            sys.exit(0)
    else:
        import fcntl

        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            sys.exit(0)

    return lock_file


if __name__ == "__main__":
    lock = acquire_single_instance_lock()
    run_app()