# Categories scaffold

This package is reserved for category predicates/annotations and
category-specific processing helpers only. Creating this scaffold does not mean
any category is active or that the collector supports one. It must not own a
final database; the single canonical user-facing lake remains
`engine/data/lake/opportunities.json`, with retained hidden rows beside it.
