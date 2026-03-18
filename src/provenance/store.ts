import * as fs from 'fs/promises';
import * as path from 'path';
import { ProvenanceRecord, ProvenanceStore } from './types';

export class JsonProvenanceStore implements ProvenanceStore {
  private readonly filePath: string;
  private readonly dirPath: string;

  constructor(repoDir: string) {
    this.dirPath = path.join(repoDir, '.aigit');
    this.filePath = path.join(this.dirPath, 'provenance.json');
  }

  private async readAll(): Promise<ProvenanceRecord[]> {
    try {
      const data = await fs.readFile(this.filePath, 'utf-8');
      return JSON.parse(data) as ProvenanceRecord[];
    } catch {
      return [];
    }
  }

  private async writeAll(records: ProvenanceRecord[]): Promise<void> {
    await fs.mkdir(this.dirPath, { recursive: true });
    // Use a unique tmp name so concurrent writes don't share the same tmp file
    const unique = `${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`;
    const tmp = `${this.filePath}.${unique}.tmp`;
    await fs.writeFile(tmp, JSON.stringify(records, null, 2), 'utf-8');
    await fs.rename(tmp, this.filePath);
  }

  async save(record: ProvenanceRecord): Promise<void> {
    const records = await this.readAll();
    records.push(record);
    await this.writeAll(records);
  }

  async load(chunkId: string): Promise<ProvenanceRecord[]> {
    const records = await this.readAll();
    return records.filter(r => r.chunkId === chunkId);
  }

  async loadAll(): Promise<ProvenanceRecord[]> {
    return this.readAll();
  }

  /**
   * Delete all provenance records for the given chunk id.
   * Returns the number of records deleted.
   */
  async delete(chunkId: string): Promise<number> {
    const records = await this.readAll();
    const remaining = records.filter(r => r.chunkId !== chunkId);
    const deleted = records.length - remaining.length;
    if (deleted > 0) await this.writeAll(remaining);
    return deleted;
  }

  /** Remove every provenance record from the store. */
  async clear(): Promise<void> {
    await this.writeAll([]);
  }
}
