import { ChunkGraph } from '../src/chunk/graph';
import { merge } from '../src/merge/engine';
import { MergeStatus, MergeStrategy } from '../src/merge/types';
import { SemanticChunk, ChunkType } from '../src/chunk/types';

function makeChunk(id: string, contentHash: string, content = ''): SemanticChunk {
  return {
    id,
    name: id,
    type: ChunkType.Function,
    filePath: 'test.ts',
    startLine: 1,
    endLine: 5,
    content: content || `function ${id}() {}`,
    contentHash,
    metadata: {},
  };
}

describe('Merge Engine', () => {
  test('only ours changed → take ours, no conflict', () => {
    const base = new ChunkGraph([makeChunk('a', 'h1')]);
    const ours = new ChunkGraph([makeChunk('a', 'h2', 'ours content')]);
    const theirs = new ChunkGraph([makeChunk('a', 'h1')]);
    const result = merge(base, ours, theirs);
    expect(result.status).toBe(MergeStatus.Success);
    expect(result.conflicts).toHaveLength(0);
    expect(result.merged.getChunk('a')?.contentHash).toBe('h2');
  });

  test('only theirs changed → take theirs, no conflict', () => {
    const base = new ChunkGraph([makeChunk('a', 'h1')]);
    const ours = new ChunkGraph([makeChunk('a', 'h1')]);
    const theirs = new ChunkGraph([makeChunk('a', 'h2', 'theirs content')]);
    const result = merge(base, ours, theirs);
    expect(result.status).toBe(MergeStatus.Success);
    expect(result.conflicts).toHaveLength(0);
    expect(result.merged.getChunk('a')?.contentHash).toBe('h2');
  });

  test('both changed the same way → no conflict', () => {
    const base = new ChunkGraph([makeChunk('a', 'h1')]);
    const ours = new ChunkGraph([makeChunk('a', 'h2', 'same content')]);
    const theirs = new ChunkGraph([makeChunk('a', 'h2', 'same content')]);
    const result = merge(base, ours, theirs);
    expect(result.status).toBe(MergeStatus.Success);
    expect(result.conflicts).toHaveLength(0);
  });

  test('both changed differently → conflict', () => {
    const base = new ChunkGraph([makeChunk('a', 'h1')]);
    const ours = new ChunkGraph([makeChunk('a', 'h2', 'ours content')]);
    const theirs = new ChunkGraph([makeChunk('a', 'h3', 'theirs content')]);
    const result = merge(base, ours, theirs);
    expect(result.status).toBe(MergeStatus.Conflict);
    expect(result.conflicts).toHaveLength(1);
    expect(result.conflicts[0].chunkId).toBe('a');
  });

  test('chunk added in ours only → include it', () => {
    const base = new ChunkGraph([makeChunk('a', 'h1')]);
    const ours = new ChunkGraph([makeChunk('a', 'h1'), makeChunk('b', 'h2')]);
    const theirs = new ChunkGraph([makeChunk('a', 'h1')]);
    const result = merge(base, ours, theirs);
    expect(result.status).toBe(MergeStatus.Success);
    expect(result.merged.getChunk('b')).toBeDefined();
  });

  test('deleted in ours but modified in theirs → conflict', () => {
    const base = new ChunkGraph([makeChunk('a', 'h1')]);
    const ours = new ChunkGraph([]); // deleted
    const theirs = new ChunkGraph([makeChunk('a', 'h2', 'modified')]); // modified
    const result = merge(base, ours, theirs);
    expect(result.status).toBe(MergeStatus.Conflict);
    expect(result.conflicts).toHaveLength(1);
  });

  test('deleted in both → do not include in merged', () => {
    const base = new ChunkGraph([makeChunk('a', 'h1'), makeChunk('b', 'h2')]);
    const ours = new ChunkGraph([makeChunk('b', 'h2')]);
    const theirs = new ChunkGraph([makeChunk('b', 'h2')]);
    const result = merge(base, ours, theirs);
    expect(result.status).toBe(MergeStatus.Success);
    expect(result.merged.hasChunk('a')).toBe(false);
    expect(result.merged.hasChunk('b')).toBe(true);
  });

  test('unchanged in all three → keep base', () => {
    const base = new ChunkGraph([makeChunk('a', 'h1')]);
    const ours = new ChunkGraph([makeChunk('a', 'h1')]);
    const theirs = new ChunkGraph([makeChunk('a', 'h1')]);
    const result = merge(base, ours, theirs);
    expect(result.status).toBe(MergeStatus.Success);
    expect(result.merged.getChunk('a')?.contentHash).toBe('h1');
  });

  test('chunk added in both with same content → no conflict', () => {
    const base = new ChunkGraph([]);
    const ours = new ChunkGraph([makeChunk('new', 'h1', 'same')]);
    const theirs = new ChunkGraph([makeChunk('new', 'h1', 'same')]);
    const result = merge(base, ours, theirs);
    expect(result.status).toBe(MergeStatus.Success);
    expect(result.merged.hasChunk('new')).toBe(true);
  });

  test('chunk added in both with different content → conflict', () => {
    const base = new ChunkGraph([]);
    const ours = new ChunkGraph([makeChunk('new', 'h1', 'ours')]);
    const theirs = new ChunkGraph([makeChunk('new', 'h2', 'theirs')]);
    const result = merge(base, ours, theirs);
    expect(result.status).toBe(MergeStatus.Conflict);
    expect(result.conflicts[0].chunkId).toBe('new');
  });

  test('conflict message is descriptive', () => {
    const base = new ChunkGraph([makeChunk('a', 'h1')]);
    const ours = new ChunkGraph([makeChunk('a', 'h2', 'ours content')]);
    const theirs = new ChunkGraph([makeChunk('a', 'h3', 'theirs content')]);
    const result = merge(base, ours, theirs);
    expect(result.conflicts[0].message).toBeTruthy();
    expect(result.conflicts[0].message.length).toBeGreaterThan(0);
  });

  test('merged size equals expected chunk count', () => {
    const base = new ChunkGraph([makeChunk('a', 'h1'), makeChunk('b', 'h2')]);
    const ours = new ChunkGraph([makeChunk('a', 'h1'), makeChunk('b', 'h2'), makeChunk('c', 'h3')]);
    const theirs = new ChunkGraph([makeChunk('a', 'h1'), makeChunk('b', 'h4')]); // b modified in theirs
    const result = merge(base, ours, theirs);
    expect(result.status).toBe(MergeStatus.Success);
    expect(result.merged.size).toBe(3);
  });

  // ── MergeStrategy tests ───────────────────────────────────────────────────

  test('strategy=Ours resolves conflict by taking ours', () => {
    const base   = new ChunkGraph([makeChunk('a', 'h1')]);
    const ours   = new ChunkGraph([makeChunk('a', 'h2', 'ours')]);
    const theirs = new ChunkGraph([makeChunk('a', 'h3', 'theirs')]);
    const result = merge(base, ours, theirs, { strategy: MergeStrategy.Ours });
    expect(result.status).toBe(MergeStatus.Success);
    expect(result.conflicts).toHaveLength(0);
    expect(result.merged.getChunk('a')?.contentHash).toBe('h2');
    expect(result.autoResolved).toBe(1);
  });

  test('strategy=Theirs resolves conflict by taking theirs', () => {
    const base   = new ChunkGraph([makeChunk('a', 'h1')]);
    const ours   = new ChunkGraph([makeChunk('a', 'h2', 'ours')]);
    const theirs = new ChunkGraph([makeChunk('a', 'h3', 'theirs')]);
    const result = merge(base, ours, theirs, { strategy: MergeStrategy.Theirs });
    expect(result.status).toBe(MergeStatus.Success);
    expect(result.merged.getChunk('a')?.contentHash).toBe('h3');
    expect(result.autoResolved).toBe(1);
  });

  test('per-chunk strategy overrides global strategy', () => {
    const base   = new ChunkGraph([makeChunk('a', 'h1'), makeChunk('b', 'h2')]);
    const ours   = new ChunkGraph([makeChunk('a', 'h3', 'a-ours'), makeChunk('b', 'h5', 'b-ours')]);
    const theirs = new ChunkGraph([makeChunk('a', 'h4', 'a-theirs'), makeChunk('b', 'h6', 'b-theirs')]);
    const result = merge(base, ours, theirs, {
      strategy: MergeStrategy.Ours,
      chunkStrategies: { b: MergeStrategy.Theirs },
    });
    expect(result.merged.getChunk('a')?.contentHash).toBe('h3'); // global: ours
    expect(result.merged.getChunk('b')?.contentHash).toBe('h6'); // override: theirs
  });

  test('result includes autoResolved and mergedEdgeCount fields', () => {
    const base = new ChunkGraph([makeChunk('a', 'h1')]);
    const ours = new ChunkGraph([makeChunk('a', 'h1')]);
    const theirs = new ChunkGraph([makeChunk('a', 'h1')]);
    const result = merge(base, ours, theirs);
    expect(typeof result.autoResolved).toBe('number');
    expect(typeof result.mergedEdgeCount).toBe('number');
  });

  // ── Edge merging tests ────────────────────────────────────────────────────

  test('edges present in both ours and theirs are included in merged', () => {
    const base = new ChunkGraph(
      [makeChunk('a', 'h1'), makeChunk('b', 'h2')],
      [{ from: 'a', to: 'b', kind: 'calls' }],
    );
    const ours = new ChunkGraph(
      [makeChunk('a', 'h1'), makeChunk('b', 'h2')],
      [{ from: 'a', to: 'b', kind: 'calls' }],
    );
    const theirs = new ChunkGraph(
      [makeChunk('a', 'h1'), makeChunk('b', 'h2')],
      [{ from: 'a', to: 'b', kind: 'calls' }],
    );
    const result = merge(base, ours, theirs);
    expect(result.mergedEdgeCount).toBe(1);
  });

  test('edge added in ours is included in merged', () => {
    const chunks = [makeChunk('a', 'h1'), makeChunk('b', 'h2')];
    const base   = new ChunkGraph(chunks, []);
    const ours   = new ChunkGraph(chunks, [{ from: 'a', to: 'b', kind: 'calls' }]);
    const theirs = new ChunkGraph(chunks, []);
    const result = merge(base, ours, theirs);
    expect(result.mergedEdgeCount).toBe(1);
  });

  test('edge deleted in both is not included in merged', () => {
    const edge = { from: 'a', to: 'b', kind: 'calls' as const };
    const chunks = [makeChunk('a', 'h1'), makeChunk('b', 'h2')];
    const base   = new ChunkGraph(chunks, [edge]);
    const ours   = new ChunkGraph(chunks, []); // deleted
    const theirs = new ChunkGraph(chunks, []); // deleted
    const result = merge(base, ours, theirs);
    expect(result.mergedEdgeCount).toBe(0);
  });
});
