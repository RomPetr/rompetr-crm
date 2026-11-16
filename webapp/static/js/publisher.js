const HOMEPAGES = {
  "The Block": "https://www.theblock.co/",
  "The Defiant": "https://thedefiant.io/",
  "Blockworks": "https://blockworks.co/",
  "CoinDesk": "https://www.coindesk.com/",
  "Decrypt": "https://decrypt.co/",
};

const select = document.querySelector("[data-publisher-select]");
const input = document.getElementById("publisher-url");
const link = document.getElementById("publisher-link");
const copyButton = document.getElementById("publisher-copy");

function updatePublisher() {
  if (!select || !input || !link) return;
  const url = HOMEPAGES[select.value] || "";
  input.value = url;
  if (url) {
    link.href = url;
    link.textContent = url;
    link.hidden = false;
    if (copyButton) copyButton.hidden = false;
  } else {
    link.removeAttribute("href");
    link.textContent = "";
    link.hidden = true;
    if (copyButton) copyButton.hidden = true;
  }
}

if (select) {
  select.addEventListener("change", updatePublisher);
  updatePublisher();
}

if (copyButton && input) {
  copyButton.addEventListener("click", async () => {
    const value = input.value;
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      copyButton.textContent = "Скопировано";
    } catch (error) {
      input.focus();
      input.select();
      try {
        document.execCommand("copy");
        copyButton.textContent = "Скопировано";
      } catch (fallbackError) {
        copyButton.textContent = "Скопируйте вручную";
      }
    }
    setTimeout(() => {
      copyButton.textContent = "Скопировать";
    }, 2000);
  });
}
