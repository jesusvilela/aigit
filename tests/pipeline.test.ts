import * as fs from 'fs/promises';
import * as os from 'os';
import * as path from 'path';
import { execSync } from 'child_process';
import { AigitPipeline } from '../src/pipeline/index';
import { SnapshotStore } from '../src/snapshot/store';
import { JsonProvenanceStore } from '../src/provenance/store';
import { ChunkGraph } from '../src/chunk/graph';
import { ChunkType, SemanticChunk } from '../src/chunk/types';
import { MergeStrategy } from '../src/merge/types';

function makeChunk(id: string, contentHash: string, content = ''): SemanticChunk {
  return {
    id, name: id, type: ChunkType.Function,
    filePath: 'test.ts', startLine: 1, endLine: 5,
    content: content || `function ${id}() {}`,
    contentHash, metadata: {},
  };
}

describe('AigitPipeline', () => {
  let tmpDir: string;
  let pipeline: AigitPipeline;
  let snapshotStore: SnapshotStore;
  let provenanceStore: JsonProvenanceStore;

  beforeEach(async () => {
    tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'aigit-pipe-'));
    // Make it a valid git repo so readWorkingFile works
    execSync('git init', { cwd: tmpDir });
    execSync('git config user.email "test@test.com"', { cwd: tmpDir });
    execSync('git config user.name "Test"', { cwd: tmpDir });

    snapshotStore  = new SnapshotStore(tmpDir);
    provenanceStore = new JsonProvenanceStore(tmpDir);
    pipeline = new AigitPipeline(tmpDir, {
      agent: { id: 'gpt-4o', name: 'GPT-4o', type: 'ai' },
      snapshotStore,
      provenanceStore,
    });
  });

  afterEach(async () => {
    await fs.rm(tmpDir, { recursive: true, force: true });
  });

  const tsContent = `
import { something } from './something';
function hello(name: string): string {
  return 'hello ' + name;
}
class Greeter {
  greet() { return 'hi'; }
}
`;

  test('run() returns graph and snapshot', async () => {
    const result = await pipeline.run('src/hello.ts', tsContent);
    expect(result.graph).toBeDefined();
    expect(result.graph.size).toBeGreaterThan(0);
    expect(result.snapshot).toBeDefined();
    expect(result.snapshot?.filePath).toBe('src/hello.ts');
  });

  test('run() without previousGraph produces no diffResult', async () => {
    const result = await pipeline.run('src/hello.ts', tsContent);
    expect(result.diffResult).toBeUndefined();
  });

  test('run() with previousGraph produces diffResult', async () => {
    const previousGraph = new ChunkGraph([makeChunk('a', 'h1')]);
    const result = await pipeline.run('src/hello.ts', tsContent, { previousGraph });
    expect(result.diffResult).toBeDefined();
    expect(typeof result.diffResult?.added).toBe('number');
  });

  test('run() records provenance for changed chunks', async () => {
    const previousGraph = new ChunkGraph([makeChunk('a', 'h1', 'function a() {}')]);
    await pipeline.run('src/hello.ts', tsContent, { previousGraph });
    const all = await provenanceStore.loadAll();
    expect(all.length).toBeGreaterThan(0);
    expect(all[0].agent.id).toBe('gpt-4o');
  });

  test('run() without snapshotStore does not save snapshot', async () => {
    const p = new AigitPipeline(tmpDir, {
      agent: { id: 'bot', name: 'Bot', type: 'ai' },
    });
    const result = await p.run('src/hello.ts', tsContent);
    expect(result.snapshot).toBeUndefined();
  });

  test('mergeGraphs() returns mergeResult and snapshot on success', async () => {
    const base   = new ChunkGraph([makeChunk('a', 'h1')]);
    const ours   = new ChunkGraph([makeChunk('a', 'h2', 'ours')]);
    const theirs = new ChunkGraph([makeChunk('a', 'h1')]);
    const result = await pipeline.mergeGraphs('src/hello.ts', base, ours, theirs);
    expect(result.mergeResult.status).toBe('success');
    expect(result.snapshot).toBeDefined();
  });

  test('mergeGraphs() does not save snapshot on conflict', async () => {
    const base   = new ChunkGraph([makeChunk('a', 'h1')]);
    const ours   = new ChunkGraph([makeChunk('a', 'h2', 'ours')]);
    const theirs = new ChunkGraph([makeChunk('a', 'h3', 'theirs')]);
    const result = await pipeline.mergeGraphs('src/hello.ts', base, ours, theirs);
    expect(result.mergeResult.status).toBe('conflict');
    expect(result.snapshot).toBeUndefined();
  });

  test('mergeGraphs() respects mergeStrategy', async () => {
    const pOurs = new AigitPipeline(tmpDir, {
      agent: { id: 'bot', name: 'Bot', type: 'ai' },
      snapshotStore,
      mergeStrategy: MergeStrategy.Ours,
    });
    const base   = new ChunkGraph([makeChunk('a', 'h1')]);
    const ours   = new ChunkGraph([makeChunk('a', 'h2', 'ours')]);
    const theirs = new ChunkGraph([makeChunk('a', 'h3', 'theirs')]);
    const result = await pOurs.mergeGraphs('f.ts', base, ours, theirs);
    expect(result.mergeResult.status).toBe('success');
    expect(result.mergeResult.merged.getChunk('a')?.contentHash).toBe('h2');
  });

  test('runFromDisk() reads file content and returns graph', async () => {
    const filePath = path.join(tmpDir, 'greeter.ts');
    await fs.writeFile(filePath, tsContent, 'utf-8');
    const result = await pipeline.runFromDisk('greeter.ts');
    expect(result.graph.size).toBeGreaterThan(0);
  });

  test('snapshot is retrievable from snapshotStore after run()', async () => {
    const { snapshot } = await pipeline.run('src/hello.ts', tsContent);
    const loaded = await snapshotStore.load(snapshot!.id);
    expect(loaded?.filePath).toBe('src/hello.ts');
  });
});
