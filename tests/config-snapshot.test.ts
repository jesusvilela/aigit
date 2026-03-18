import * as fs from 'fs/promises';
import * as os from 'os';
import * as path from 'path';
import {
  AigitError,
  ParseError,
  GraphCycleError,
  MergeConflictError,
  ConfigError,
} from '../src/errors';
import { readConfig, writeConfig, initConfig, AigitConfig } from '../src/config';
import { SnapshotStore } from '../src/snapshot/store';
import { ChunkGraph } from '../src/chunk/graph';
import { SemanticChunk, ChunkType } from '../src/chunk/types';

// ─── Error types ──────────────────────────────────────────────────────────────

describe('Error types', () => {
  test('AigitError has correct name and code', () => {
    const err = new AigitError('test', 'TEST_CODE');
    expect(err.name).toBe('AigitError');
    expect(err.code).toBe('TEST_CODE');
    expect(err.message).toBe('test');
    expect(err instanceof Error).toBe(true);
  });

  test('ParseError captures filePath and optional line', () => {
    const err = new ParseError('bad syntax', 'src/foo.ts', 10);
    expect(err.name).toBe('ParseError');
    expect(err.code).toBe('PARSE_ERROR');
    expect(err.filePath).toBe('src/foo.ts');
    expect(err.line).toBe(10);
    expect(err instanceof AigitError).toBe(true);
  });

  test('GraphCycleError captures cycle ids', () => {
    const err = new GraphCycleError(['a', 'b', 'a']);
    expect(err.name).toBe('GraphCycleError');
    expect(err.code).toBe('GRAPH_CYCLE');
    expect(err.cycleIds).toEqual(['a', 'b', 'a']);
    expect(err.message).toContain('a → b → a');
  });

  test('MergeConflictError captures conflict ids', () => {
    const err = new MergeConflictError(['chunk-1', 'chunk-2']);
    expect(err.name).toBe('MergeConflictError');
    expect(err.code).toBe('MERGE_CONFLICT');
    expect(err.conflictIds).toEqual(['chunk-1', 'chunk-2']);
    expect(err.message).toContain('2');
  });

  test('ConfigError has correct name and code', () => {
    const err = new ConfigError('no config found');
    expect(err.name).toBe('ConfigError');
    expect(err.code).toBe('CONFIG_ERROR');
  });
});

// ─── Config ───────────────────────────────────────────────────────────────────

describe('Config (file-system)', () => {
  let tmpDir: string;

  beforeEach(async () => {
    tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'aigit-cfg-'));
  });

  afterEach(async () => {
    await fs.rm(tmpDir, { recursive: true, force: true });
  });

  test('readConfig throws ConfigError when not initialised', async () => {
    await expect(readConfig(tmpDir)).rejects.toThrow(ConfigError);
  });

  test('initConfig creates config file and returns config', async () => {
    const config = await initConfig(tmpDir);
    expect(config.initialized).toBe(true);
    expect(config.version).toBeTruthy();
    const configPath = path.join(tmpDir, '.aigit', 'config.json');
    const raw = await fs.readFile(configPath, 'utf-8');
    expect(JSON.parse(raw).initialized).toBe(true);
  });

  test('initConfig is idempotent (does not overwrite existing config)', async () => {
    await initConfig(tmpDir);
    const custom: AigitConfig = {
      version: '99.0.0',
      initialized: true,
      metadata: { custom: true },
    };
    await writeConfig(tmpDir, custom);
    const again = await initConfig(tmpDir);
    expect(again.version).toBe('99.0.0');
  });

  test('writeConfig + readConfig round-trip', async () => {
    const cfg: AigitConfig = {
      version: '1.2.3',
      initialized: true,
      defaultAgent: { id: 'bot', name: 'Bot', type: 'ai' },
    };
    await writeConfig(tmpDir, cfg);
    const loaded = await readConfig(tmpDir);
    expect(loaded).toEqual(cfg);
  });

  test('readConfig throws ConfigError on corrupt JSON', async () => {
    const aigitDir = path.join(tmpDir, '.aigit');
    await fs.mkdir(aigitDir, { recursive: true });
    await fs.writeFile(path.join(aigitDir, 'config.json'), 'NOT_JSON', 'utf-8');
    await expect(readConfig(tmpDir)).rejects.toThrow(ConfigError);
  });
});

// ─── Snapshot ─────────────────────────────────────────────────────────────────

describe('SnapshotStore (file-system)', () => {
  let tmpDir: string;
  let store: SnapshotStore;

  function makeGraph(ids: string[]): ChunkGraph {
    const chunks: SemanticChunk[] = ids.map(id => ({
      id,
      name: id,
      type: ChunkType.Function,
      filePath: 'test.ts',
      startLine: 1,
      endLine: 3,
      content: `function ${id}() {}`,
      contentHash: `hash_${id}`,
      metadata: {},
    }));
    return new ChunkGraph(chunks);
  }

  beforeEach(async () => {
    tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'aigit-snap-'));
    store = new SnapshotStore(tmpDir);
  });

  afterEach(async () => {
    await fs.rm(tmpDir, { recursive: true, force: true });
  });

  test('save creates a snapshot and returns metadata', async () => {
    const graph = makeGraph(['a', 'b']);
    const snap = await store.save('src/foo.ts', graph);
    expect(snap.id).toMatch(/^[0-9a-f]{40}$/);
    expect(snap.filePath).toBe('src/foo.ts');
    expect(snap.timestamp).toBeTruthy();
    expect(snap.graph.chunks).toHaveLength(2);
  });

  test('load retrieves saved snapshot', async () => {
    const graph = makeGraph(['x']);
    const saved = await store.save('foo.ts', graph);
    const loaded = await store.load(saved.id);
    expect(loaded?.id).toBe(saved.id);
    expect(loaded?.filePath).toBe('foo.ts');
  });

  test('load returns undefined for unknown id', async () => {
    const result = await store.load('nonexistent-id');
    expect(result).toBeUndefined();
  });

  test('loadGraph reconstructs ChunkGraph', async () => {
    const graph = makeGraph(['a', 'b', 'c']);
    const saved = await store.save('g.ts', graph);
    const restored = await store.loadGraph(saved.id);
    expect(restored).toBeDefined();
    expect(restored?.size).toBe(3);
    expect(restored?.hasChunk('a')).toBe(true);
  });

  test('list returns all snapshots sorted newest-first', async () => {
    const snap1 = await store.save('a.ts', makeGraph(['a']));
    const snap2 = await store.save('b.ts', makeGraph(['b']));
    const list = await store.list();
    expect(list).toHaveLength(2);
    // Both snapshots must be present; verify sort is newest-first by timestamp comparison
    const timestamps = list.map(s => s.timestamp);
    expect(timestamps[0] >= timestamps[1]).toBe(true);
    // Check we got the right files (either order is acceptable if timestamps are equal)
    expect(list.map(s => s.filePath).sort()).toEqual(['a.ts', 'b.ts'].sort());
    void snap1; void snap2;
  });

  test('list returns empty array when no snapshots exist', async () => {
    expect(await store.list()).toEqual([]);
  });

  test('delete removes snapshot', async () => {
    const snap = await store.save('d.ts', makeGraph(['d']));
    const deleted = await store.delete(snap.id);
    expect(deleted).toBe(true);
    expect(await store.load(snap.id)).toBeUndefined();
  });

  test('delete returns false for unknown id', async () => {
    const result = await store.delete('no-such-id');
    expect(result).toBe(false);
  });

  test('save with commitSha stores it in snapshot', async () => {
    const snap = await store.save('x.ts', makeGraph(['x']), { commitSha: 'abc123' });
    const loaded = await store.load(snap.id);
    expect(loaded?.commitSha).toBe('abc123');
  });
});
