# AIGit ruleset version 1

The committed `.semantic/ruleset.yaml` is the semantic constitution used to
construct a canonical snapshot graph. Chunking fails before reading source
files when the ruleset does not conform to this schema.

## Schema

All fields are required. Unknown and duplicate fields are rejected.

| Field | Allowed value |
| --- | --- |
| `version` | `1` |
| `parsers` | Mapping of lowercase file extensions to parser backends, plus required `default` |
| `identity.strategy` | `path+anchor+type` |
| `identity.false_positive_policy` | `prefer-new-node` |
| `canonicalization.line_endings` | `lf` |
| `canonicalization.trim_trailing_whitespace` | `true` |

Parser keys other than `default` must start with `.`. Supported backends are
`python-ast`, `markdown-headings`, `json-keys`, `yaml-keys`,
`typescript-ast`, and `file`. An extension not explicitly mapped uses the
`default` backend.

Line endings and trailing whitespace are normalized before parser dispatch.
Paths stored in semantic artifacts use POSIX separators. Canonical snapshot
identity does not consult a previous chunk index; lineage is a separate
operation.

## Reproducibility context

`.semantic/build_context.json` records the exact ruleset digest, semantic
schema, parser registry digest, canonicalizer version, and AIGit version.
Incremental cache entries are reusable only when this complete context
matches.
