const crypto = require('crypto');

function createJobRegistry() {
  const jobs = new Map();

  function create({ videoId, sourceFile }) {
    const id = crypto.randomUUID();
    const job = {
      id,
      videoId,
      sourceFile,
      state: 'pending',
      error: null,
      stage: null,
      createdAt: new Date().toISOString(),
      startedAt: null,
      finishedAt: null,
    };
    jobs.set(id, job);
    return job;
  }

  function get(id) {
    return jobs.get(id) || null;
  }

  function update(id, patch) {
    const job = jobs.get(id);
    if (!job) return null;
    Object.assign(job, patch);
    if (patch.state === 'running' && !job.startedAt) {
      job.startedAt = new Date().toISOString();
    }
    if ((patch.state === 'completed' || patch.state === 'failed') && !job.finishedAt) {
      job.finishedAt = new Date().toISOString();
    }
    return job;
  }

  function findActiveByVideoId(videoId) {
    for (const job of jobs.values()) {
      if (job.videoId === videoId && (job.state === 'pending' || job.state === 'running')) {
        return job;
      }
    }
    return null;
  }

  function list() {
    // newest first by creation time
    return [...jobs.values()].sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1));
  }

  return { create, get, update, findActiveByVideoId, list };
}

module.exports = { createJobRegistry };
