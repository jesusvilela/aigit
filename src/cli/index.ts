#!/usr/bin/env node
import { Command } from 'commander';
import * as fs from 'fs/promises';
import * as path from 'path';
import { GitAdapter } from '../git/adapter';
import { parse } from '../chunk/parser';
import { ChunkGraph } from '../chunk/graph';
import { diff } from '../diff/engine';
import { merge } from '../merge/engine';
import { JsonProvenanceStore } from '../provenance/store';
import { ProvenanceTracker } from '../provenance/tracker';

const program = new Command();

program
  .name('aigit')
  .description('AI-native semantic version control layer built on top of Git')
  .version('0.1.0');

program
  .command('init [repoPath]')
  .description('Initialize aigit in a repository')
  .action(async (repoPath: string = '.') => {
    const resolvedPath = path.resolve(repoPath);
    const aigitDir = path.join(resolvedPath, '.aigit');
    await fs.mkdir(aigitDir, { recursive: true });
    await fs.writeFile(
      path.join(aigitDir, 'config.json'),
      JSON.stringify({ version: '0.1.0', initialized: true }, null, 2),
      'utf-8'
    );
    console.log(`Initialized aigit in ${aigitDir}`);
  });

program
  .command('diff [commitA] [commitB] [file]')
  .description('Semantic diff between two commits')
  .action(async (commitA: string, commitB: string, file: string) => {
    const cwd = process.cwd();
    const adapter = new GitAdapter(cwd);

    try {
      if (!commitA || !commitB || !file) {
        console.error('Usage: aigit diff <commitA> <commitB> <file>');
        process.exit(1);
      }

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

      console.log(JSON.stringify(result, null, 2));
    } catch (e) {
      console.error('Error:', (e as Error).message);
      process.exit(1);
    }
  });

program
  .command('merge <base> <ours> <theirs>')
  .description('Semantic three-way merge')
  .option('-f, --file <file>', 'File to merge')
  .action(async (baseRef: string, oursRef: string, theirsRef: string, options: { file?: string }) => {
    const cwd = process.cwd();
    const adapter = new GitAdapter(cwd);

    try {
      const file = options.file;
      if (!file) {
        console.error('Usage: aigit merge <base> <ours> <theirs> --file <file>');
        process.exit(1);
      }

      const [baseHash, oursHash, theirsHash] = await Promise.all([
        adapter.getCommitHash(baseRef),
        adapter.getCommitHash(oursRef),
        adapter.getCommitHash(theirsRef),
      ]);

      const [baseContent, oursContent, theirsContent] = await Promise.all([
        adapter.getBlob(baseHash, file),
        adapter.getBlob(oursHash, file),
        adapter.getBlob(theirsHash, file),
      ]);

      const baseGraph = new ChunkGraph(parse(baseContent, file));
      const oursGraph = new ChunkGraph(parse(oursContent, file));
      const theirsGraph = new ChunkGraph(parse(theirsContent, file));

      const result = merge(baseGraph, oursGraph, theirsGraph);
      console.log(JSON.stringify(result, null, 2));
    } catch (e) {
      console.error('Error:', (e as Error).message);
      process.exit(1);
    }
  });

program
  .command('provenance [chunkId]')
  .description('Show provenance records')
  .action(async (chunkId: string | undefined) => {
    const cwd = process.cwd();
    const store = new JsonProvenanceStore(cwd);
    const tracker = new ProvenanceTracker(store);

    if (chunkId) {
      const history = await tracker.history(chunkId);
      console.log(JSON.stringify(history, null, 2));
    } else {
      const all = await tracker.listAll();
      console.log(JSON.stringify(all, null, 2));
    }
  });

program.parse(process.argv);
