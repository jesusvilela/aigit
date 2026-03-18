import * as fs from 'fs/promises';
import * as path from 'path';
import * as crypto from 'crypto';
import { Snapshot } from './types';
import { ChunkGraph } from '../chunk/graph';

function snapDir(repoDir: string): string {
  return path.join(repoDir, '.aigit', 'snapshots');
}

function snapFile(repoDir: string, id: string): string {
  return path.join(snapDir(repoDir), `${id}.json`);
}

/**
 * Persistent store for ChunkGraph snapshots under `.aigit/snapshots/`.
 */
export class SnapshotStore {
  constructor(private readonly repoDir: string) {}

  /**
   * Save a ChunkGraph as a named snapshot.
   * Returns the created Snapshot (including the generated id).
   */
  async save(
    filePath: string,
    graph: ChunkGraph,
    options: { commitSha?: string; metadata?: Record<string, unknown> } = {},
  ): Promise<Snapshot> {
    const timestamp = new Date().toISOString();
    const id = crypto
      .createHash('sha1')
      .update(`${timestamp}:${filePath}`)
      .digest('hex');

    const snapshot: Snapshot = {
      id,
      timestamp,
      filePath,
      commitSha: options.commitSha,
      graph: graph.toJSON(),
      metadata: options.metadata,
    };

    await fs.mkdir(snapDir(this.repoDir), { recursive: true });
    const unique = `${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`;
    const tmp = `${snapFile(this.repoDir, id)}.${unique}.tmp`;
    await fs.writeFile(tmp, JSON.stringify(snapshot, null, 2), 'utf-8');
    await fs.rename(tmp, snapFile(this.repoDir, id));

    return snapshot;
  }

  /**
   * Load a snapshot by id.
   * Returns `undefined` if no snapshot with that id exists.
   */
  async load(id: string): Promise<Snapshot | undefined> {
    try {
      const raw = await fs.readFile(snapFile(this.repoDir, id), 'utf-8');
      return JSON.parse(raw) as Snapshot;
    } catch {
      return undefined;
    }
  }

  /**
   * Load a snapshot by id and reconstruct the ChunkGraph from it.
   */
  async loadGraph(id: string): Promise<ChunkGraph | undefined> {
    const snapshot = await this.load(id);
    if (!snapshot) return undefined;
    return ChunkGraph.fromJSON(snapshot.graph);
  }

  /**
   * List all snapshot metadata (without full graph payload) sorted newest-first.
   */
  async list(): Promise<Array<Omit<Snapshot, 'graph'>>> {
    try {
      const dir = snapDir(this.repoDir);
      const entries = await fs.readdir(dir);
      const snapshots: Snapshot[] = [];

      await Promise.all(
        entries
          .filter(e => e.endsWith('.json'))
          .map(async e => {
            try {
              const raw = await fs.readFile(path.join(dir, e), 'utf-8');
              snapshots.push(JSON.parse(raw) as Snapshot);
            } catch {
              // skip corrupt entries
            }
          }),
      );

      return snapshots
        .sort((a, b) => b.timestamp.localeCompare(a.timestamp))
        .map(({ graph: _graph, ...rest }) => rest);
    } catch {
      return [];
    }
  }

  /**
   * Delete a snapshot by id.
   * Returns `true` if deleted, `false` if it did not exist.
   */
  async delete(id: string): Promise<boolean> {
    try {
      await fs.unlink(snapFile(this.repoDir, id));
      return true;
    } catch {
      return false;
    }
  }
}
