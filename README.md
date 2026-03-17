# aigit

> **A safe semantic chunk graph for AI workflows, built on top of Git.**
>
> Semantic diff, merge, and provenance for AI-generated changes—without replacing Git.

aigit adds a semantic layer on top of Git: it parses source code into **named, typed chunks** (functions, classes, methods, etc.), builds a **deterministic chunk graph**, and enables **semantic diffs, three-way merges, and agent provenance tracking**—all stored alongside your existing Git history.

---

## Features

| Feature | Description |
|---|---|
| **Semantic chunking** | Parse JS/TS/Python into named chunks (functions, classes, methods, imports, variables) |
| **Chunk graph (DAG)** | Represent relationships between chunks as a directed acyclic graph |
| **Semantic diff** | Diff two versions at chunk level: Added / Removed / Modified / Renamed / Unchanged |
| **Three-way merge** | Merge two branches at chunk boundaries, detecting true conflicts |
| **Agent provenance** | Tag every chunk change with agent identity, timestamp, and commit SHA |
| **Git native** | Works on top of any Git repo—reads blobs, resolves refs, writes git-notes |

---

## Installation

```bash
npm install -g aigit
```

Or run locally from this repo:

```bash
npm install
npm run build
npm link   # makes `aigit` available globally
```

---

## Quick Start

### Initialize

```bash
cd my-project
aigit init
# → Initialized aigit in .aigit/
```

### Semantic Diff

```bash
aigit diff HEAD~1 HEAD src/utils.ts
```

Output (JSON):

```json
{
  "diffs": [
    { "kind": "modified", "before": { "name": "computeHash", "type": "function", ... }, "after": { ... } },
    { "kind": "added",    "after":  { "name": "validateInput", "type": "function", ... } }
  ],
  "added": 1, "removed": 0, "modified": 1, "renamed": 0, "unchanged": 3
}
```

### Three-way Semantic Merge

```bash
aigit merge main feature-branch HEAD --file src/api.ts
```

### Provenance

```bash
# Show all records
aigit provenance

# Show history for a specific chunk
aigit provenance <chunkId>
```

---

## Architecture

```
src/
├── chunk/
│   ├── types.ts     – ChunkType enum, SemanticChunk & ChunkEdge interfaces
│   ├── parser.ts    – Language-aware regex parser (JS/TS/Python)
│   └── graph.ts     – ChunkGraph class (add/query/topologicalSort/JSON)
├── diff/
│   ├── types.ts     – DiffKind enum, ChunkDiff & SemanticDiffResult
│   └── engine.ts    – diff(before, after) → SemanticDiffResult
├── merge/
│   ├── types.ts     – MergeStatus enum, MergeConflict & SemanticMergeResult
│   └── engine.ts    – merge(base, ours, theirs) → SemanticMergeResult
├── provenance/
│   ├── types.ts     – AgentIdentity, ProvenanceRecord & ProvenanceStore interfaces
│   ├── tracker.ts   – ProvenanceTracker (record / query / history / listAll)
│   └── store.ts     – JsonProvenanceStore (persists to .aigit/provenance.json)
├── git/
│   └── adapter.ts   – GitAdapter (getBlob, getCommitHash, getStagedFiles, notes)
├── cli/
│   └── index.ts     – CLI commands (init / diff / merge / provenance)
└── index.ts         – Public API re-exports
```

### Core Types

```typescript
// A named, typed unit of code
interface SemanticChunk {
  id: string;          // sha1("filePath:name:type")
  name: string;
  type: ChunkType;     // function | class | method | interface | variable | import | block
  filePath: string;
  startLine: number;
  endLine: number;
  content: string;
  contentHash: string; // sha1(content)
  metadata: Record<string, unknown>;
}

// A directed relationship between chunks
interface ChunkEdge {
  from: string;  // chunk id
  to: string;    // chunk id
  kind: 'calls' | 'imports' | 'extends' | 'implements' | 'uses';
}

// An agent provenance record
interface ProvenanceRecord {
  chunkId: string;
  agentId: string;
  agentName: string;
  action: 'created' | 'modified' | 'deleted' | 'reviewed';
  commitSha?: string;
  timestamp: string;  // ISO 8601
  metadata?: Record<string, unknown>;
}
```

---

## Programmatic API

```typescript
import { parse, ChunkGraph, diff, merge, ProvenanceTracker, JsonProvenanceStore } from 'aigit';

// Parse a file into semantic chunks
const chunks = parse(sourceCode, 'src/utils.ts');

// Build a graph
const graph = new ChunkGraph(chunks);

// Semantic diff
const result = diff(graphBefore, graphAfter);
console.log(result.added, result.modified, result.removed);

// Three-way merge
const { status, merged, conflicts } = merge(baseGraph, oursGraph, theirsGraph);

// Record provenance
const store = new JsonProvenanceStore('/path/to/repo');
const tracker = new ProvenanceTracker(store);
await tracker.record({
  chunkId: chunks[0].id,
  agentId: 'gpt-4o',
  agentName: 'OpenAI GPT-4o',
  action: 'modified',
  commitSha: 'abc123',
});
```

---

## Development

```bash
npm install        # install dependencies
npm run build      # compile TypeScript → dist/
npm test           # run all 28 tests
npm run lint       # type-check only (tsc --noEmit)
```

---

## Design Goals

- **Non-destructive** – aigit never modifies your Git history; it only adds metadata (`.aigit/` directory, optional git-notes).
- **Deterministic** – chunk IDs are content-addressed (`sha1(filePath:name:type)`), making graphs reproducible.
- **Language-agnostic** – the parser supports JS/TS/Python today; more languages can be added via the `parse()` extension point.
- **Composable** – every layer (chunk, diff, merge, provenance) is an independent module with a stable TypeScript interface.

---

## License

MIT
