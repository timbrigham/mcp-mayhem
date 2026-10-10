# AI inventory fidelity: example

This is a single-author proof of concept, built for and used in one dedicated environment. It demonstrates the measurement; it is not a production or complete tool.

## The metric

An inventory lists the components of an AI system: prompt templates, tool definitions,
guardrail configurations, and model and dataset references. Each active component has a name
and a SHA-256 hash of its content; components taken out of service are listed as retired.
The tool scans the deployed system and compares, name by name, without changing the inventory.

Each name falls in exactly one class:

| class | inventory | deployed |
|---|---|---|
| matched (m) | active | present, same hash |
| modified (d) | active | present, different hash |
| vanished (v) | active | absent |
| phantom (p) | not listed | present |
| resurrected (z) | retired | present |
| retired-absent | retired | absent (correct; not counted) |

- precision = m / (m + d + v): of the components the inventory lists as active, the share
  deployed exactly as recorded.
- recall = m / (m + d + p + z): of the components deployed, the share the inventory describes
  correctly.

A ratio whose denominator is 0 is reported as null. Names are matched exactly, so a component
renamed without updating the inventory counts as one vanished and one phantom. Text files are
hashed with line endings normalised to LF; JSON files are hashed after sorting keys.

## Run it

From the `inventoryFidelity/` directory:

```
python examples/inventory-fidelity/run_example.py
```

The script writes a small agent repository to a new temporary directory and prints that
directory's path on stderr. It registers four components (a system prompt, two tools and a
guardrail policy) and lists one retired tool. It then builds a deployed copy where the prompt
is edited, the guardrail policy is missing, a new tool was added and the retired tool is back,
and measures it. Output:

```
AI inventory fidelity
  inventory  inventory.json
  artifact   deployed

Locations scanned
  prompts/*.md                         1 item(s)
  tools/*.json                         4 item(s)
  guardrails/*.yaml, guardrails/*.yml  absent
  models.json                          absent

Classes
  matched         2  tools/lookup.json, tools/search.json
  modified        1  prompts/system.md
  vanished        1  guardrails/policy.yaml
  phantom         1  tools/browse.json
  resurrected     1  tools/legacy.json
  retired-absent  0  -  (correct; not counted in the ratios)

  precision  m/(m+d+v)    2/4 = 0.5
  recall     m/(m+d+p+z)  2/5 = 0.4

Errors: none
```

Add `--json` to that command for the same report as JSON.

## On your own system

```
python -m inventory_fidelity register --root <artifact-dir> <path> [<path> ...]
python -m inventory_fidelity measure --inventory <inventory.json> --artifact <artifact-dir>
```

`register` prints inventory entries using the same hash routine as `measure`. Exit codes:
0 measured; 2 could not measure (missing or unreadable input, or an invalid inventory);
3 measured, but some deployed items could not be classified and are listed as errors;
64 the command line itself was malformed.

## Requirements

Python 3.11 or later. Standard library only; nothing to install, and git is not needed.
