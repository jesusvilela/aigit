#!/usr/bin/env node
import { Command } from 'commander';
import * as path from 'path';
import { GitAdapter } from '../git/adapter';
import { parse } from '../chunk/parser';
import { ChunkGraph } from '../chunk/graph';
import { diff } from '../diff/engine';
import { DiffKind } from '../diff/types';
import { merge } from '../merge/engine';
import { MergeStatus } from '../merge/types';
import { JsonProvenanceStore } from '../provenance/store';
import { ProvenanceTracker } from '../provenance/tracker';
import { SnapshotStore } from '../snapshot/store';
import { initConfig, readConfig } from '../config';

const program = new Command();

program
  .name('aigit')
  .description('AI-native semantic version control layer built on top of Git')
  .version('0.1.0');

// ─── init ────────────────────────────────────────────────────────────────────

program
  .command('init [repoPath]')
  .description('Initialize aigit in a repository')
  .action(async (repoPath: string = '.') => {
    const resolvedPath = path.resolve(repoPath);
    try {
      const config = await initConfig(resolvedPath);
      console.log(`Initialized aigit v${config.version} in ${path.join(resolvedPath, '.aigit')}`);
    } catch (e) {
      console.error('Error:', (e as Error).message);
      process.exit(1);
    }
  });

// ─── diff ─────────────────────────────────────────────────────────────────────

program
  .command('diff <commitA> <commitB> <file>')
  .description('Semantic diff between two commits')
  .option('--format <fmt>', 'Output format: json | text', 'text')
  .action(async (commitA: string, commitB: string, file: string, options: { format: string }) => {
    const cwd = process.cwd();
    const adapter = new GitAdapter(cwd);

    try {
      const [hashA, hashB] = await Promise.all([
        adapter.getCommitHash(commitA),
        adapter.getCommitHash(commitB),
      ]);

      const [contentA, contentB] = await Promise.all([
        adapter.getBlob(hashA, file),
        adapter.getBlob(hashB, file),
      ]);

      const chunksA = parse(contentA, file);
      const chunksB = parse(contentB, file);
      const graphA = new ChunkGraph(chunksA);
      const graphB = new ChunkGraph(chunksB);
      const result = diff(graphA, graphB);

      if (options.format === 'json') {
        console.log(JSON.stringify(result, null, 2));
      } else {
        console.log(`Semantic diff: ${commitA.slice(0, 7)}..${commitB.slice(0, 7)} — ${file}`);
        console.log(`  +${result.added} added  -${result.removed} removed  ~${result.modified} modified  ↪${result.renamed} renamed  =${result.unchanged} unchanged\n`);
        for (const d of result.diffs) {
          if (d.kind === DiffKind.Added)     console.log(`  + [${d.after?.type}] ${d.after?.name}`);
          if (d.kind === DiffKind.Removed)   console.log(`  - [${d.before?.type}] ${d.before?.name}`);
          if (d.kind === DiffKind.Modified)  console.log(`  ~ [${d.before?.type}] ${d.before?.name}`);
          if (d.kind === DiffKind.Renamed)   console.log(`  ↪ [${d.before?.type}] ${d.before?.name} → ${d.after?.name}`);
        }
      }
    } catch (e) {
      console.error('Error:', (e as Error).message);
      process.exit(1);
    }
  });

// ─── merge ────────────────────────────────────────────────────────────────────

program
  .command('merge <base> <ours> <theirs>')
  .description('Semantic three-way merge')
  .requiredOption('-f, --file <file>', 'File to merge')
  .option('--format <fmt>', 'Output format: json | text', 'text')
  .action(async (
    baseRef: string,
    oursRef: string,
    theirsRef: string,
    options: { file: string; format: string },
  ) => {
    const cwd = process.cwd();
    const adapter = new GitAdapter(cwd);

    try {
      const [baseHash, oursHash, theirsHash] = await Promise.all([
        adapter.getCommitHash(baseRef),
        adapter.getCommitHash(oursRef),
        adapter.getCommitHash(theirsRef),
      ]);

      const [baseContent, oursContent, theirsContent] = await Promise.all([
        adapter.getBlob(baseHash, options.file),
        adapter.getBlob(oursHash, options.file),
        adapter.getBlob(theirsHash, options.file),
      ]);

      const baseGraph   = new ChunkGraph(parse(baseContent,   options.file));
      const oursGraph   = new ChunkGraph(parse(oursContent,   options.file));
      const theirsGraph = new ChunkGraph(parse(theirsContent, options.file));

      const result = merge(baseGraph, oursGraph, theirsGraph);

      if (options.format === 'json') {
        console.log(JSON.stringify(result, null, 2));
      } else {
        const status = result.status === MergeStatus.Success ? '✓ Clean merge' : '✗ Conflicts';
        console.log(`${status} — ${options.file}`);
        console.log(`  Merged chunks: ${result.merged.size}`);
        if (result.conflicts.length > 0) {
          console.log(`  Conflicts (${result.conflicts.length}):`);
          for (const c of result.conflicts) {
            console.log(`    ✗ ${c.chunkId}: ${c.message}`);
          }
          process.exit(1);
        }
      }
    } catch (e) {
      console.error('Error:', (e as Error).message);
      process.exit(1);
    }
  });

// ─── provenance ───────────────────────────────────────────────────────────────

program
  .command('provenance [chunkId]')
  .description('Show provenance records')
  .option('--format <fmt>', 'Output format: json | text', 'text')
  .action(async (chunkId: string | undefined, options: { format: string }) => {
    const cwd = process.cwd();
    const store = new JsonProvenanceStore(cwd);
    const tracker = new ProvenanceTracker(store);

    try {
      const records = chunkId
        ? await tracker.history(chunkId)
        : await tracker.listAll();

      if (options.format === 'json') {
        console.log(JSON.stringify(records, null, 2));
      } else {
        if (records.length === 0) {
          console.log('No provenance records found.');
          return;
        }
        for (const r of records) {
          console.log(`[${r.timestamp}] ${r.action} — chunk: ${r.chunkId}`);
          console.log(`  agent: ${r.agent.name} (${r.agent.id}, type: ${r.agent.type})`);
          if (r.commitSha) console.log(`  commit: ${r.commitSha}`);
        }
      }
    } catch (e) {
      console.error('Error:', (e as Error).message);
      process.exit(1);
    }
  });

// ─── snapshot ─────────────────────────────────────────────────────────────────

program
  .command('snapshot')
  .description('Manage chunk-graph snapshots')
  .addCommand(
    new Command('create')
      .description('Create a snapshot of a file\'s semantic graph')
      .argument('<file>', 'Source file to snapshot')
      .option('--commit <sha>', 'Associate snapshot with a commit SHA')
      .option('--format <fmt>', 'Output format: json | text', 'text')
      .action(async (file: string, options: { commit?: string; format: string }) => {
        const cwd = process.cwd();
        const adapter = new GitAdapter(cwd);
        const snapStore = new SnapshotStore(cwd);

        try {
          const content = await adapter.readWorkingFile(file);
          const chunks = parse(content, file);
          const graph = new ChunkGraph(chunks);
          const snapshot = await snapStore.save(file, graph, { commitSha: options.commit });

          if (options.format === 'json') {
            // eslint-disable-next-line @typescript-eslint/no-unused-vars
            const { graph: _g, ...meta } = snapshot;
            console.log(JSON.stringify(meta, null, 2));
          } else {
            console.log(`Snapshot created: ${snapshot.id}`);
            console.log(`  file: ${snapshot.filePath}  chunks: ${graph.size}`);
          }
        } catch (e) {
          console.error('Error:', (e as Error).message);
          process.exit(1);
        }
      }),
  )
  .addCommand(
    new Command('list')
      .description('List all snapshots')
      .option('--format <fmt>', 'Output format: json | text', 'text')
      .action(async (options: { format: string }) => {
        const cwd = process.cwd();
        const snapStore = new SnapshotStore(cwd);

        try {
          const snapshots = await snapStore.list();
          if (options.format === 'json') {
            console.log(JSON.stringify(snapshots, null, 2));
          } else {
            if (snapshots.length === 0) {
              console.log('No snapshots found.');
              return;
            }
            for (const s of snapshots) {
              console.log(`${s.id.slice(0, 8)}  ${s.timestamp.slice(0, 19)}  ${s.filePath}`);
            }
          }
        } catch (e) {
          console.error('Error:', (e as Error).message);
          process.exit(1);
        }
      }),
  )
  .addCommand(
    new Command('diff')
      .description('Diff two snapshots by id')
      .argument('<idA>', 'First snapshot id')
      .argument('<idB>', 'Second snapshot id')
      .option('--format <fmt>', 'Output format: json | text', 'text')
      .action(async (idA: string, idB: string, options: { format: string }) => {
        const cwd = process.cwd();
        const snapStore = new SnapshotStore(cwd);

        try {
          const [graphA, graphB] = await Promise.all([
            snapStore.loadGraph(idA),
            snapStore.loadGraph(idB),
          ]);
          if (!graphA) { console.error(`Snapshot not found: ${idA}`); process.exit(1); }
          if (!graphB) { console.error(`Snapshot not found: ${idB}`); process.exit(1); }

          const result = diff(graphA, graphB);
          if (options.format === 'json') {
            console.log(JSON.stringify(result, null, 2));
          } else {
            console.log(`Snapshot diff: ${idA.slice(0, 8)} → ${idB.slice(0, 8)}`);
            console.log(`  +${result.added} added  -${result.removed} removed  ~${result.modified} modified  ↪${result.renamed} renamed`);
          }
        } catch (e) {
          console.error('Error:', (e as Error).message);
          process.exit(1);
        }
      }),
  );

// ─── config ───────────────────────────────────────────────────────────────────

program
  .command('config')
  .description('Show the aigit config for the current repo')
  .option('--format <fmt>', 'Output format: json | text', 'text')
  .action(async (options: { format: string }) => {
    const cwd = process.cwd();
    try {
      const config = await readConfig(cwd);
      if (options.format === 'json') {
        console.log(JSON.stringify(config, null, 2));
      } else {
        console.log(`aigit v${config.version}`);
        console.log(`  initialized: ${config.initialized}`);
        if (config.defaultAgent) {
          console.log(`  default agent: ${config.defaultAgent.name} (${config.defaultAgent.id})`);
        }
      }
    } catch (e) {
      console.error('Error:', (e as Error).message);
      process.exit(1);
    }
  });

// ─── log ──────────────────────────────────────────────────────────────────────

program
  .command('log [file]')
  .description('Show recent Git commits with semantic context')
  .option('-n, --count <n>', 'Number of commits', '10')
  .option('--format <fmt>', 'Output format: json | text', 'text')
  .action(async (file: string | undefined, options: { count: string; format: string }) => {
    const cwd = process.cwd();
    const adapter = new GitAdapter(cwd);

    try {
      const entries = await adapter.getLog({
        maxCount: parseInt(options.count, 10),
        file,
      });

      if (options.format === 'json') {
        console.log(JSON.stringify(entries, null, 2));
      } else {
        for (const e of entries) {
          console.log(`${e.hash.slice(0, 7)}  ${e.date.slice(0, 10)}  ${e.author}  ${e.message}`);
        }
      }
    } catch (e) {
      console.error('Error:', (e as Error).message);
      process.exit(1);
    }
  });

program.parse(process.argv);
