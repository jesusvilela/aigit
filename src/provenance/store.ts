import * as fs from 'fs/promises';
import * as path from 'path';
import { ProvenanceRecord, ProvenanceStore } from './types';

export class JsonProvenanceStore implements ProvenanceStore {
  private filePath: string;
  private dirPath: string;

  constructor(repoDir: string) {
    this.dirPath = path.join(repoDir, '.aigit');
    this.filePath = path.join(this.dirPath, 'provenance.json');
  }

  async save(record: ProvenanceRecord): Promise<void> {
    await fs.mkdir(this.dirPath, { recursive: true });
    let records: ProvenanceRecord[] = [];
    try {
      const data = await fs.readFile(this.filePath, 'utf-8');
      records = JSON.parse(data);
    } catch {
      records = [];
    }
    records.push(record);
    await fs.writeFile(this.filePath, JSON.stringify(records, null, 2), 'utf-8');
  }

  async load(chunkId: string): Promise<ProvenanceRecord[]> {
    try {
      const data = await fs.readFile(this.filePath, 'utf-8');
      const records: ProvenanceRecord[] = JSON.parse(data);
      return records.filter(r => r.chunkId === chunkId);
    } catch {
      return [];
    }
  }

  async loadAll(): Promise<ProvenanceRecord[]> {
    try {
      const data = await fs.readFile(this.filePath, 'utf-8');
      return JSON.parse(data);
    } catch {
      return [];
    }
  }
}
