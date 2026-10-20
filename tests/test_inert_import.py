"""Tests that importing unwrapt is inert.

The build backend imports the package to read the version, and the
autowrapt entry point loads unwrapt.bootstrap before calling it, so
importing either module must install nothing and import nothing beyond
the standard library: no hook, no wrapt.
"""


def test_import_does_not_install_the_hook() -> None:
    import unwrapt

    assert unwrapt.is_installed() is False

    # The real inertness check runs in a subprocess, because this test
    # process may have imported wrapt through pytest's own machinery.

    from support import run_facts

    facts = run_facts(
        """
        import builtins, sys

        before = builtins.__import__

        import unwrapt

        facts = {
            "import_unchanged": builtins.__import__ is before,
            "wrapt_imported": "wrapt" in sys.modules,
            "installed": unwrapt.is_installed(),
            "version": unwrapt.__version__,
        }
        print(__import__("json").dumps(facts))
        """
    )

    assert facts["import_unchanged"] is True
    assert facts["wrapt_imported"] is False
    assert facts["installed"] is False
    assert facts["version"] == unwrapt.__version__


def test_import_bootstrap_does_not_install_the_hook() -> None:
    from support import run_facts

    facts = run_facts(
        """
        import builtins, sys

        before = builtins.__import__

        import unwrapt.bootstrap

        facts = {
            "import_unchanged": builtins.__import__ is before,
            "wrapt_imported": "wrapt" in sys.modules,
            "installed": unwrapt.is_installed(),
        }
        print(__import__("json").dumps(facts))
        """
    )

    assert facts["import_unchanged"] is True
    assert facts["wrapt_imported"] is False
    assert facts["installed"] is False
