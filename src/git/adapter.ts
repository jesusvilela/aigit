import simpleGit, { SimpleGit } from 'simple-git';
import * as fs from 'fs/promises';
import * as path from 'path';

export class GitAdapter {
  private git: SimpleGit;
  private repoPath: string;

  constructor(repoPath: string) {
    this.repoPath = repoPath;
    this.git = simpleGit(repoPath);
  }

  async getCommitHash(ref: string): Promise<string> {
    const hash = await this.git.revparse([ref]);
    return hash.trim();
  }

  async getBlob(commitSha: string, filePath: string): Promise<string> {
    return this.git.raw(['show', `${commitSha}:${filePath}`]);
  }

  async getStagedFiles(): Promise<string[]> {
    const output = await this.git.diff(['--name-only', '--cached']);
    return output.trim().split('\n').filter(f => f.length > 0);
  }

  async readWorkingFile(filePath: string): Promise<string> {
    return fs.readFile(path.join(this.repoPath, filePath), 'utf-8');
  }

  async writeNote(objectSha: string, message: string): Promise<void> {
    await this.git.raw(['notes', 'add', '-m', message, objectSha]);
  }

  async listNotes(): Promise<Array<{notesSha: string, objectSha: string}>> {
    const output = await this.git.raw(['notes', 'list']);
    if (!output.trim()) return [];
    return output.trim().split('\n').map(line => {
      const [notesSha, objectSha] = line.trim().split(/\s+/);
      return { notesSha, objectSha };
    });
  }
}
