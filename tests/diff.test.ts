import { ChunkGraph } from '../src/chunk/graph';
import { diff } from '../src/diff/engine';
import { DiffKind } from '../src/diff/types';
import { SemanticChunk, ChunkType } from '../src/chunk/types';

function makeChunk(id: string, contentHash: string): SemanticChunk {
  return {
    id,
    name: id,
    type: ChunkType.Function,
    filePath: 'test.ts',
    startLine: 1,
    endLine: 5,
    content: `function ${id}() {}`,
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

  test('modified chunk', () => {
    const before = new ChunkGraph([makeChunk('a', 'h1')]);
    const after = new ChunkGraph([makeChunk('a', 'h2')]);
    const result = diff(before, after);
    expect(result.modified).toBe(1);
    const modDiff = result.diffs.find(d => d.kind === DiffKind.Modified);
    expect(modDiff?.before?.id).toBe('a');
    expect(modDiff?.after?.id).toBe('a');
  });

  test('renamed chunk', () => {
    const before = new ChunkGraph([makeChunk('a', 'h1')]);
    const after = new ChunkGraph([makeChunk('b', 'h1')]); // same content hash, different id
    const result = diff(before, after);
    expect(result.renamed).toBe(1);
    const renamedDiff = result.diffs.find(d => d.kind === DiffKind.Renamed);
    expect(renamedDiff?.before?.id).toBe('a');
    expect(renamedDiff?.after?.id).toBe('b');
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
});
