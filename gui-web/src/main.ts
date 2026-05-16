import App from './App.svelte';
import './app.css';

const app = new App({
  target: document.getElementById('app')!,
});

// PWA: service worker 登録 (存在すれば)
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/service-worker.js')
      .catch((e) => console.warn('SW register failed', e));
  });
}

export default app;
