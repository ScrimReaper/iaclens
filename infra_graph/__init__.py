"""iaclens: Knowledge graph for infrastructure files."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("iaclens")
except PackageNotFoundError:  # running from a source tree
    __version__ = "0.4.0"
