import { Hono } from 'hono';
import { listVideos, getVideo } from '../lib/catalog';

export const videos = new Hono();

videos.get('/', (c) => {
  try {
    return c.json(listVideos());
  } catch (e) {
    console.error('listVideos failed', e);
    return c.json([]);
  }
});

videos.get('/:id', (c) => {
  const id = c.req.param('id');
  const v = getVideo(id);
  if (!v) return c.json({ error: 'not_found' }, 404);
  return c.json(v);
});
