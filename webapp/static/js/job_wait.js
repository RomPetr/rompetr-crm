const panel = document.getElementById("job-wait");
if (panel) {
  const started = Date.parse(panel.dataset.started || "");
  const timer = document.getElementById("job-timer");
  const hint = document.getElementById("job-hint");

  function tick() {
    if (!timer) return;
    const seconds = Number.isNaN(started)
      ? 0
      : Math.max(0, Math.floor((Date.now() - started) / 1000));
    timer.textContent = String(seconds);
    if (hint && seconds > 90) hint.hidden = false;
  }

  tick();
  setInterval(tick, 1000);
}
