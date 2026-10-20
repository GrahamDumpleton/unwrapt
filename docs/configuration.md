# Configuration

Every environment variable unwrapt reads, in one place. All of them are
optional, and an invalid value warns once on stderr and falls back to
its default rather than stopping the host application: a configuration
mistake must never break startup.

## Activation

Activation is not an environment variable of unwrapt's own:
`AUTOWRAPT_BOOTSTRAP=unwrapt` is read by
[autowrapt](autowrapt.md), the companion that injects unwrapt at
interpreter startup. unwrapt itself has one activation, the explicit
`unwrapt.install()` described on the [API](api.md) page, and importing
the package is always inert.

## Shim mode

`UNWRAPT_CONFIG` = *path*

: A JSON file of extra lazy candidates, for imports in modules whose
source you do not control. See the
[external configuration](external-config.md) page for the format and
rules.

  On Python 3.15 and later this is the only candidate source, and
  supplying it is what activates unwrapt there: with no configuration
  unwrapt installs nothing. See
  [Python 3.15](python-3-15.md).

`UNWRAPT_CONFIG_ONLY` = 1

: Ignore each module's own `__lazy_modules__` and use only the external
configuration. An A/B switch for experiments, on any Python version.
On 3.15 the behaviour is always configuration-only, so the variable
makes no difference there.

`UNWRAPT_DEBUG` = 1

: Log to stderr the active mode at startup, and each deferred import
as it happens:

  ```
  unwrapt: shim mode installed
  unwrapt: deferring 'xml.dom' in myapp.web
  ```

  On 3.15 without a configuration the debug line says so, and there
  is no warning: that case is normal, not a problem.

## Profile mode

Profile mode is documented on its own [page](profile-mode.md), with
the [strategy guide](choosing-what-to-defer.md) as the way to use its
report. The variables:

`UNWRAPT_PROFILE` = 1

: Enable profile mode: install the recording hook instead of the
shim hook. No deferral happens. The two modes are mutually exclusive
in one process, by design: profiling an already-deferred program
measures something different.

`UNWRAPT_PROFILE_OUTPUT` = *path*

: Where the report goes, with `%p` expanding to the process id. The
default is stderr. The path form is the recommended one: worker
process setups (a mod_wsgi daemon process, for example) may not run
exit handlers reliably, and one file per process keeps concurrent
workers from interleaving their reports.

`UNWRAPT_PROFILE_FORMAT` = text | json

: The report form: text (the default) or JSON. The JSON form is what
the [AI assistant procedure](ai-assisted-tuning.md) and the
`python -m unwrapt.report` tool consume.

`UNWRAPT_PROFILE_MIN_MS` = *n*

: Hide candidate rows whose cumulative time is below *n*
milliseconds, in the text report. The JSON keeps every edge; the
filter is a display filter.

`UNWRAPT_PROFILE_PACKAGES` = a,b

: Restrict the text report's candidate rows to importers under these
top-level packages, treating the rest as not editable. Useful when
the profile covers a lot of third-party code you will never change.

## Booleans

The flag variables accept, case-insensitively, `1`, `true`, `yes` and
`on` as true; an empty value, `0`, `false`, `no` and `off` as false;
and anything else warns once and reads as not set.
