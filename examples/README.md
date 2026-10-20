# Examples

Small runnable programs, one question each:

- [shim-demo](shim-demo/): the simplest run on a Python below 3.15, an
  application declaring one import lazy in its own source.

- [external-config-demo](external-config-demo/): deferring an import
  in code you do not want to edit, with a JSON configuration.

- [profile-demo](profile-demo/): running an application under profile
  mode and reading the report.

- [python-3-15-demo](python-3-15-demo/): native lazy imports and
  unwrapt's external configuration dividing the work on 3.15+.

- [worked-example](worked-example/): the sample application the
  documentation's strategy guide walks end to end.

Each directory's README says exactly how to run it and what to expect.
The worked example also runs in CI, so what its README promises is
what its code does.
