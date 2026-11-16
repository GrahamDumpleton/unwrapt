"""A downstream-style check that the public API is typed.

This file is not a test: it is type-checked by the project's mypy
configuration (its files list includes tests/), and it is named so
pytest does not collect it. It stands in for a downstream package that
imports unwrapt and relies on its annotations, which is what shipping
py.typed promises.
"""

import importlib.metadata
from collections.abc import Callable

import unwrapt

version: str = unwrapt.__version__
installed: bool = unwrapt.is_installed()

# The metadata version and the package version must agree; a downstream
# type checker should accept comparing them without casts.

distribution_version: str = importlib.metadata.version("unwrapt")

if distribution_version != version:
    raise RuntimeError("version mismatch")

# The configuration API loads through the package's module __getattr__,
# and must still be visible to a downstream type checker.

config: unwrapt.Config = unwrapt.Config(lazy_modules={"shop.web": ["decimal"]})
options: unwrapt.ProfileOptions = config.profile
found: str | None = unwrapt.find_config()
loaded: unwrapt.Config = unwrapt.load_config(found)
error: type[Exception] = unwrapt.ConfigError
install_from_env: Callable[[], bool] = unwrapt.install_from_env
layers: unwrapt.Installed | None = unwrapt.installed()
uninstall: Callable[[], bool] = unwrapt.uninstall
explicit: bool = unwrapt.install(config, defer=True, profile=False)
