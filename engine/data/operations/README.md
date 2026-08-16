# Operations data

This directory contains resolver inputs/snapshots, run and tier state, and
page-reader processing outputs. `pagereader_rows.json` is an operational
processing/compatibility output, not a second final opportunity lake. The only
canonical final user-facing stores are `../lake/opportunities.json` and its
retained non-default companion `../lake/hidden.json`.
