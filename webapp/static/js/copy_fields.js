document.querySelectorAll("[data-copy-target]").forEach((button) => {
  const field = document.getElementById(button.dataset.copyTarget);
  if (!field) return;

  button.addEventListener("click", async () => {
    const label = button.textContent;
    try {
      await navigator.clipboard.writeText(field.value);
    } catch (error) {
      field.focus();
      field.select();
      try {
        document.execCommand("copy");
      } catch (fallbackError) {
        button.textContent = "Скопируйте вручную";
        setTimeout(() => {
          button.textContent = label;
        }, 2000);
        return;
      }
    }
    button.textContent = "Скопировано";
    setTimeout(() => {
      button.textContent = label;
    }, 2000);
  });
});
