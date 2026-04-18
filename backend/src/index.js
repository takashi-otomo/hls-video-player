const path = require('path');
const { createApp } = require('./app');

const PORT = parseInt(process.env.PORT || '3000', 10);
const MEDIA_ROOT = process.env.MEDIA_ROOT || path.resolve(__dirname, '../../media');
const FRONTEND_ROOT = process.env.FRONTEND_ROOT || path.resolve(__dirname, '../../frontend/public');

const app = createApp({ mediaRoot: MEDIA_ROOT, frontendRoot: FRONTEND_ROOT });

app.listen(PORT, () => {
  console.log(`[hls-video-player] listening on http://localhost:${PORT}`);
  console.log(`[hls-video-player] media root: ${MEDIA_ROOT}`);
  console.log(`[hls-video-player] frontend root: ${FRONTEND_ROOT}`);
});
