import { Hono } from 'hono';
import { loadFavorites, toggleFavorite, setFavorite } from '../lib/favorites';

export const favorites = new Hono();

favorites.get('/', (c) => {
  return c.json({ favorites: Array.from(loadFavorites()).sort() });
});

favorites.post('/:id', async (c) => {
  const id = c.req.param('id');
  let body: { favorited?: boolean } | null = null;
  try {
    body = await c.req.json();
  } catch {
    body = null;
  }
  let next: boolean;
  if (body && typeof body.favorited === 'boolean') {
    next = setFavorite(id, body.favorited);
  } else {
    next = toggleFavorite(id);
  }
  return c.json({ id, isFavorite: next });
});
