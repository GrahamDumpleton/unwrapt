"""The autowrapt bootstrap entry point: zero-code injection.

Two opt-ins gate this path, and both live outside unwrapt. The
autowrapt package must be installed, whose startup hook (a PEP 829
.start file on Python 3.15 and later, a .pth file before that) is
what makes interpreter startup do anything at all, and
AUTOWRAPT_BOOTSTRAP=unwrapt must be set in the environment. The
variable's value names an entry point group that autowrapt hands to
wrapt.discover_post_import_hooks() once site initialisation completes:
each entry in the group maps a trigger module to a callback fired when
that module is imported. unwrapt's entry hooks the os module, which is
always already imported by then, so the callback fires immediately, at
startup, before the application's own imports. Absent either opt-in,
the entry point in unwrapt's metadata is inert, and unwrapt itself
never imports autowrapt and has no dependency on it.

When it fires, bootstrap() hands over to unwrapt.install(), which
resolves the mode from the environment and installs the hook, or
declines to, per the Python version rules there.
"""

from unwrapt import install


def bootstrap(module: object = None) -> bool:
    """Install the unwrapt import hook at interpreter startup.

    Fired as a wrapt post import hook when the environment opts in;
    module is the trigger module the hook convention passes (os, per
    the entry point) and carries no information. Injection never takes
    the process down: a configuration problem warns and the process
    starts without deferral.

    Returns True when a hook was installed, False otherwise.
    """

    return install()
