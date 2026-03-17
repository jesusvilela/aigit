import { ChunkGraph } from '../src/chunk/graph';
import { merge } from '../src/merge/engine';
import { MergeStatus } from '../src/merge/types';
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
});
