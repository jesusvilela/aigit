import { ChunkGraph } from '../src/chunk/graph';
import { diff } from '../src/diff/engine';
import { DiffKind, EdgeDiffKind } from '../src/diff/types';
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

describe('Diff Engine', () => {
  test('identical graphs → all unchanged', () => {
    const g = new ChunkGraph([makeChunk('a', 'h1'), makeChunk('b', 'h2')]);
    const result = diff(g, g);
    expect(result.unchanged).toBe(2);
    expect(result.added).toBe(0);
    expect(result.removed).toBe(0);
    expect(result.modified).toBe(0);
    expect(result.renamed).toBe(0);
  });

  test('added chunk', () => {
    const before = new ChunkGraph([makeChunk('a', 'h1')]);
    const after = new ChunkGraph([makeChunk('a', 'h1'), makeChunk('b', 'h2')]);
    const result = diff(before, after);
    expect(result.added).toBe(1);
    const addedDiff = result.diffs.find(d => d.kind === DiffKind.Added);
    expect(addedDiff?.after?.id).toBe('b');
  });

  test('removed chunk', () => {
    const before = new ChunkGraph([makeChunk('a', 'h1'), makeChunk('b', 'h2')]);
    const after = new ChunkGraph([makeChunk('a', 'h1')]);
    const result = diff(before, after);
    expect(result.removed).toBe(1);
    const removedDiff = result.diffs.find(d => d.kind === DiffKind.Removed);
    expect(removedDiff?.before?.id).toBe('b');
  });

  test('modified chunk includes similarity score', () => {
    const before = new ChunkGraph([makeChunk('a', 'h1', 'function a() { return 1; }')]);
    const after  = new ChunkGraph([makeChunk('a', 'h2', 'function a() { return 2; }')]);
    const result = diff(before, after);
    expect(result.modified).toBe(1);
    const modDiff = result.diffs.find(d => d.kind === DiffKind.Modified);
    expect(modDiff?.similarity).toBeDefined();
    expect(modDiff?.similarity).toBeGreaterThan(0);
    expect(modDiff?.similarity).toBeLessThanOrEqual(1);
  });

  test('exact-hash rename', () => {
    const before = new ChunkGraph([makeChunk('a', 'h1')]);
    const after = new ChunkGraph([makeChunk('b', 'h1')]); // same content hash, different id
    const result = diff(before, after);
    expect(result.renamed).toBe(1);
    const renamedDiff = result.diffs.find(d => d.kind === DiffKind.Renamed);
    expect(renamedDiff?.before?.id).toBe('a');
    expect(renamedDiff?.after?.id).toBe('b');
    expect(renamedDiff?.similarity).toBe(1.0);
  });

  test('fuzzy rename by content similarity', () => {
    // Different id AND different hash but very similar content
    const before = new ChunkGraph([
      makeChunk('oldFn', 'h1', 'function process(items) { return items.map(x => x * 2); }'),
    ]);
    const after = new ChunkGraph([
      makeChunk('newFn', 'h2', 'function process(items) { return items.map(x => x * 3); }'),
    ]);
    const result = diff(before, after);
    // Should be detected as a rename (not add+remove) due to high similarity
    expect(result.renamed).toBe(1);
    const renamedDiff = result.diffs.find(d => d.kind === DiffKind.Renamed);
    expect(renamedDiff?.similarity).toBeGreaterThan(0.5);
  });

  test('counts are correct for mixed scenario', () => {
    const before = new ChunkGraph([
      makeChunk('unchanged', 'h1'),
      makeChunk('modified', 'h2'),
      makeChunk('removed', 'h3'),
      makeChunk('renamed_old', 'h4'),
    ]);
    const after = new ChunkGraph([
      makeChunk('unchanged', 'h1'),
      makeChunk('modified', 'h2_new'),
      makeChunk('added', 'h5'),
      makeChunk('renamed_new', 'h4'),
    ]);
    const result = diff(before, after);
    expect(result.unchanged).toBe(1);
    expect(result.modified).toBe(1);
    expect(result.removed).toBe(1);
    expect(result.renamed).toBe(1);
    expect(result.added).toBe(1);
  });

  test('summary statistics are computed', () => {
    const before = new ChunkGraph([makeChunk('a', 'h1'), makeChunk('b', 'h2')]);
    const after  = new ChunkGraph([makeChunk('a', 'h3'), makeChunk('c', 'h4')]);
    const result = diff(before, after);
    expect(result.summary).toBeDefined();
    expect(result.summary.totalChunks).toBe(3); // a(modified) + b(removed) + c(added)
    expect(result.summary.changedChunks).toBe(3);
    expect(result.summary.changePercentage).toBe(100);
    expect(result.summary.dominantKind).toBeDefined();
  });

  test('summary changePercentage is 0 for identical graphs', () => {
    const g = new ChunkGraph([makeChunk('a', 'h1')]);
    const result = diff(g, g);
    expect(result.summary.changePercentage).toBe(0);
  });

  test('edge diffs: added edge', () => {
    const before = new ChunkGraph(
      [makeChunk('a', 'h1'), makeChunk('b', 'h2')],
      [],
    );
    const after = new ChunkGraph(
      [makeChunk('a', 'h1'), makeChunk('b', 'h2')],
      [{ from: 'a', to: 'b', kind: 'calls' }],
    );
    const result = diff(before, after);
    const addedEdge = result.edgeDiffs.find(e => e.kind === EdgeDiffKind.Added);
    expect(addedEdge).toBeDefined();
    expect(addedEdge?.edge.from).toBe('a');
  });

  test('edge diffs: removed edge', () => {
    const before = new ChunkGraph(
      [makeChunk('a', 'h1'), makeChunk('b', 'h2')],
      [{ from: 'a', to: 'b', kind: 'calls' }],
    );
    const after = new ChunkGraph(
      [makeChunk('a', 'h1'), makeChunk('b', 'h2')],
      [],
    );
    const result = diff(before, after);
    const removedEdge = result.edgeDiffs.find(e => e.kind === EdgeDiffKind.Removed);
    expect(removedEdge).toBeDefined();
  });

  test('edge diffs: unchanged edge', () => {
    const edges = [{ from: 'a', to: 'b', kind: 'calls' as const }];
    const before = new ChunkGraph([makeChunk('a', 'h1'), makeChunk('b', 'h2')], edges);
    const after  = new ChunkGraph([makeChunk('a', 'h1'), makeChunk('b', 'h2')], edges);
    const result = diff(before, after);
    const unchanged = result.edgeDiffs.filter(e => e.kind === EdgeDiffKind.Unchanged);
    expect(unchanged).toHaveLength(1);
  });

  test('empty before and after → all zero', () => {
    const result = diff(new ChunkGraph(), new ChunkGraph());
    expect(result.added).toBe(0);
    expect(result.removed).toBe(0);
    expect(result.modified).toBe(0);
    expect(result.renamed).toBe(0);
    expect(result.unchanged).toBe(0);
    expect(result.edgeDiffs).toHaveLength(0);
  });
});
