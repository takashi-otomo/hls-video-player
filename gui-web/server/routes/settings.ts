import { Hono } from 'hono';
import { existsSync } from 'fs';
import { getLibraryRoot, setLibraryRoot, validateLibraryRoot } from '../lib/settings';

export const settings = new Hono();

settings.get('/', (c) => {
  const lib = getLibraryRoot();
  return c.json({ library_root: lib, exists: existsSync(lib) });
});

settings.post('/library_root', async (c) => {
  let body: { library_root?: string };
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: 'invalid JSON body' }, 400);
  }
  const p = body.library_root ?? '';
  const { ok, message } = validateLibraryRoot(p);
  if (!ok) return c.json({ error: message }, 400);
  const saved = setLibraryRoot(p);
  return c.json({ library_root: saved, message });
});
