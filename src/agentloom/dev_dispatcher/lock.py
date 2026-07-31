"""Cross-process lock for serial repository mutation."""

import os
import subprocess
from pathlib import Path
from types import TracebackType


class DispatcherLock:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self._owned = False

    def __enter__(self) -> "DispatcherLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = self._acquire()
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(str(os.getpid()))
        self._owned = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._owned:
            self.path.unlink(missing_ok=True)
            self._owned = False

    def _acquire(self) -> int:
        try:
            return os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            try:
                owner_pid = int(self.path.read_text(encoding="ascii"))
            except (OSError, ValueError):
                owner_pid = -1
            if self._process_exists(owner_pid):
                message = f"Development dispatcher is already running: {self.path}"
                raise RuntimeError(message) from error
            self.path.unlink(missing_ok=True)
            try:
                return os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError as retry_error:
                message = f"Development dispatcher is already running: {self.path}"
                raise RuntimeError(message) from retry_error

    @staticmethod
    def _process_exists(pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            completed = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                check=False,
                shell=False,
                text=True,
                capture_output=True,
                timeout=10,
            )
            return completed.returncode == 0 and f'"{pid}"' in completed.stdout
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
