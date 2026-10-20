# Profile mode demo

Running the sample application under profile mode to find what its
imports cost and what is worth deferring, then reading the strategy
guide's method on the report.

```console
$ pip install unwrapt autowrapt
$ AUTOWRAPT_BOOTSTRAP=unwrapt UNWRAPT_PROFILE=1 python app.py
```

The text report prints to stderr at process exit. Write it to a file
instead, in the JSON form the strategy guide and the AI assistant
procedure consume:

```console
$ AUTOWRAPT_BOOTSTRAP=unwrapt UNWRAPT_PROFILE=1 UNWRAPT_PROFILE_FORMAT=json \
    UNWRAPT_PROFILE_OUTPUT=report.json python app.py

$ python -m unwrapt.report report.json
```

Start with the summary header (how big the prize is), then the heavy
modules, then the import chains, and only then the flat candidate list:
the [choosing what to defer](https://unwrapt.readthedocs.io/en/latest/choosing-what-to-defer.html)
guide explains how to turn what you see into decisions.
