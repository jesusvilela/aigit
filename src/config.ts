import * as fs from 'fs/promises';
import * as path from 'path';
import { ConfigError } from './errors';

export interface AigitConfig {
  version: string;
  initialized: boolean;
  /** Default agent identity used when recording provenance without an explicit agent. */
  defaultAgent?: {
    id: string;
    name: string;
    type: 'human' | 'ai' | 'system';
  };
  /** Languages to parse. Defaults to all supported languages when absent. */
  languages?: Array<'ts' | 'js' | 'tsx' | 'jsx' | 'py'>;
  /** Additional metadata persisted alongside config. */
  metadata?: Record<string, unknown>;
}

const CONFIG_VERSION = '0.1.0';
const CONFIG_FILENAME = 'config.json';

function configPath(repoDir: string): string {
  return path.join(repoDir, '.aigit', CONFIG_FILENAME);
}

/**
 * Read the aigit config for the given repo directory.
 * Throws `ConfigError` if the file is missing or malformed.
 */
export async function readConfig(repoDir: string): Promise<AigitConfig> {
  const filePath = configPath(repoDir);
  let raw: string;
  try {
    raw = await fs.readFile(filePath, 'utf-8');
  } catch {
    throw new ConfigError(
      `aigit is not initialised in '${repoDir}'. Run 'aigit init' first.`,
    );
  }
  try {
    return JSON.parse(raw) as AigitConfig;
  } catch {
    throw new ConfigError(`Config file is corrupt: ${filePath}`);
  }
}

/**
 * Write an aigit config to disk (overwrites any existing config).
 */
export async function writeConfig(
  repoDir: string,
  config: AigitConfig,
): Promise<void> {
  const aigitDir = path.join(repoDir, '.aigit');
  await fs.mkdir(aigitDir, { recursive: true });
  const filePath = configPath(repoDir);
  const tmp = `${filePath}.${Date.now().toString(36)}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(config, null, 2), 'utf-8');
  await fs.rename(tmp, filePath);
}

/**
 * Initialise aigit in the given repo directory.
 * If a config already exists it is left unchanged.
 * Returns the config that is now in effect.
 */
export async function initConfig(repoDir: string): Promise<AigitConfig> {
  try {
    return await readConfig(repoDir);
  } catch {
    const config: AigitConfig = {
      version: CONFIG_VERSION,
      initialized: true,
    };
    await writeConfig(repoDir, config);
    return config;
  }
}
