const panel = document.getElementById("job-wait");
if (panel) {
  const started = Date.parse(panel.dataset.started || "");
  const timer = document.getElementById("job-timer");
  const hint = document.getElementById("job-hint");
  const postId = panel.dataset.postId;
  const jobId = panel.dataset.jobId;

  function tick() {
    if (!timer) return;
    const seconds = Number.isNaN(started)
      ? 0
      : Math.max(0, Math.floor((Date.now() - started) / 1000));
    timer.textContent = String(seconds);
    if (hint && seconds > 90) hint.hidden = false;
  }

  async function poll() {
    if (!postId || !jobId) return;
    try {
      const response = await fetch(`/drafts/${postId}/jobs/${jobId}/status`, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      if (!response.ok) return;
      const data = await response.json();
      if (data.status && !["queued", "running"].includes(data.status)) {
        window.location.reload();
      }
    } catch (error) {
      // сеть недоступна — продолжаем опрос
    }
  }

  tick();
  setInterval(tick, 1000);
  poll();
  setInterval(poll, 2000);
}
