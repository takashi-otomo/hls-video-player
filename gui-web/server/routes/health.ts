import { Hono } from 'hono';
import { existsSync } from 'fs';
import { getLibraryRoot } from '../lib/settings';

export const health = new Hono();

health.get('/', (c) => {
  const lib = getLibraryRoot();
  return c.json({
    ok: true,
    library_root: lib,
    library_root_exists: existsSync(lib),
  });
});
