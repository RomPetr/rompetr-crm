document.querySelectorAll("[data-toggle-target]").forEach((checkbox) => {
  const target = document.getElementById(checkbox.dataset.toggleTarget);
  if (!target) return;

  function sync() {
    if (checkbox.disabled) {
      target.disabled = true;
      target.classList.add("disabled-field");
      return;
    }
    target.disabled = !checkbox.checked;
    target.classList.toggle("disabled-field", !checkbox.checked);
  }

  checkbox.addEventListener("change", sync);
  sync();
});
