import subprocess
from importlib.metadata import PackageNotFoundError, version


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def _package_version() -> str:
    try:
        return version("struudel")
    except PackageNotFoundError:
        return "dev"


VERSION = _package_version()
COMMIT = _git_commit()
