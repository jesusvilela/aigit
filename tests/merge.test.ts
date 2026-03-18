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
    // a: unchanged, b: take theirs, c: added in ours
    expect(result.merged.size).toBe(3);
  });
});
