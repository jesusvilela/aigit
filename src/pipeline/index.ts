import { ChunkGraph } from '../chunk/graph';
import { parse } from '../chunk/parser';
import { diff } from '../diff/engine';
import { SemanticDiffResult } from '../diff/types';
import { merge } from '../merge/engine';
import { MergeOptions } from '../merge/engine';
import { SemanticMergeResult, MergeStrategy } from '../merge/types';
import { ProvenanceTracker } from '../provenance/tracker';
import { ProvenanceStore } from '../provenance/types';
import { AgentIdentity } from '../provenance/types';
import { SnapshotStore } from '../snapshot/store';
import { Snapshot } from '../snapshot/types';
import { GitAdapter } from '../git/adapter';

export interface PipelineOptions {
  /** Agent identity for provenance recording. */
  agent?: AgentIdentity;
  /** Snapshot store to use. If omitted, no snapshots are saved. */
  snapshotStore?: SnapshotStore;
  /** Provenance store to use. If omitted, no provenance is recorded. */
  provenanceStore?: ProvenanceStore;
  /** Merge strategy to pass through when running merge. */
  mergeStrategy?: MergeStrategy;
}

export interface PipelineRunResult {
  /** The parsed graph of the current file version. */
  graph: ChunkGraph;
  /** Diff against the previous graph (if a `previousGraph` was provided). */
  diffResult?: SemanticDiffResult;
  /** The snapshot saved, if a `SnapshotStore` was configured. */
  snapshot?: Snapshot;
}

export interface PipelineMergeResult {
  mergeResult: SemanticMergeResult;
  snapshot?: Snapshot;
}

/**
 * High-level pipeline that chains: parse → diff → provenance → snapshot.
 *
 * Example:
 * ```ts
 * const pipeline = new AigitPipeline(repoPath, {
 *   agent: { id: 'gpt-4o', name: 'GPT-4o', type: 'ai' },
 *   snapshotStore: new SnapshotStore(repoPath),
 *   provenanceStore: new JsonProvenanceStore(repoPath),
 * });
 *
 * const result = await pipeline.run('src/api.ts', content, { previousGraph });
 * ```
 */
export class AigitPipeline {
  private readonly git: GitAdapter;
  private readonly tracker?: ProvenanceTracker;
  private readonly snapshotStore?: SnapshotStore;
  private readonly options: PipelineOptions;

  constructor(repoPath: string, options: PipelineOptions = {}) {
    this.options = options;
    this.git = new GitAdapter(repoPath);
    if (options.provenanceStore) {
      this.tracker = new ProvenanceTracker(options.provenanceStore);
    }
    if (options.snapshotStore) {
      this.snapshotStore = options.snapshotStore;
    }
  }

  /**
   * Parse `content` for `filePath`, optionally diff against `previousGraph`,
   * record provenance for changed chunks, and save a snapshot.
   */
  async run(
    filePath: string,
    content: string,
    opts: {
      previousGraph?: ChunkGraph;
      commitSha?: string;
      metadata?: Record<string, unknown>;
    } = {},
  ): Promise<PipelineRunResult> {
    const chunks = parse(content, filePath);
    const graph  = new ChunkGraph(chunks);

    let diffResult: SemanticDiffResult | undefined;

    if (opts.previousGraph) {
      diffResult = diff(opts.previousGraph, graph);

      if (this.tracker && this.options.agent) {
        const agent = this.options.agent;
        const records: Promise<void>[] = [];

        for (const d of diffResult.diffs) {
          const chunkId =
            d.after?.id ??
            d.before?.id;

          if (!chunkId) continue;

          let action: 'created' | 'modified' | 'deleted';
          switch (d.kind) {
            case 'added':   action = 'created';  break;
            case 'removed': action = 'deleted';  break;
            default:        action = 'modified'; break;
          }

          records.push(
            this.tracker.record({
              chunkId,
              agent,
              action,
              commitSha: opts.commitSha,
              metadata: opts.metadata,
            }),
          );
        }
        await Promise.all(records);
      }
    }

    let snapshot: Snapshot | undefined;
    if (this.snapshotStore) {
      snapshot = await this.snapshotStore.save(filePath, graph, {
        commitSha: opts.commitSha,
        metadata: opts.metadata,
      });
    }

    return { graph, diffResult, snapshot };
  }

  /**
   * Three-way semantic merge via the pipeline.
   * Optionally saves a snapshot of the merged result.
   */
  async mergeGraphs(
    filePath: string,
    base: ChunkGraph,
    ours: ChunkGraph,
    theirs: ChunkGraph,
    opts: { commitSha?: string; metadata?: Record<string, unknown> } = {},
  ): Promise<PipelineMergeResult> {
    const mergeOptions: MergeOptions = this.options.mergeStrategy
      ? { strategy: this.options.mergeStrategy }
      : {};

    const mergeResult = merge(base, ours, theirs, mergeOptions);

    let snapshot: Snapshot | undefined;
    if (this.snapshotStore && mergeResult.status === 'success') {
      snapshot = await this.snapshotStore.save(filePath, mergeResult.merged, {
        commitSha: opts.commitSha,
        metadata: { ...opts.metadata, mergedAt: new Date().toISOString() },
      });
    }

    return { mergeResult, snapshot };
  }

  /**
   * Run the pipeline for the working-tree version of a file.
   * Reads the file from disk via GitAdapter.
   */
  async runFromDisk(
    filePath: string,
    opts: { previousGraph?: ChunkGraph; commitSha?: string } = {},
  ): Promise<PipelineRunResult> {
    const content = await this.git.readWorkingFile(filePath);
    return this.run(filePath, content, opts);
  }
}
