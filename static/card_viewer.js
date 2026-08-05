/* Full-size card artwork viewer shared by search and collection pages. */
"use strict";

(() => {
  const modal = document.getElementById("art-modal");
  if (!modal) return;
  const image = document.getElementById("art-modal-image");
  const title = document.getElementById("art-modal-title");
  const code = document.getElementById("art-modal-code");

  function close() {
    modal.classList.add("hidden");
    image.removeAttribute("src");
  }

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-card-art]");
    if (!trigger) return;
    const cardKey = trigger.dataset.cardKey || "";
    const source = trigger.currentSrc || trigger.src
      || (cardKey ? `/api/card_img/${cardKey}` : "");
    if (!source) return;
    image.src = source;
    image.alt = trigger.dataset.cardName || trigger.alt || "Riftbound card";
    title.textContent = trigger.dataset.cardName || "Riftbound card";
    code.textContent = cardKey;
    modal.classList.remove("hidden");
  });

  document.getElementById("art-modal-close").addEventListener("click", close);
  modal.addEventListener("click", (event) => {
    if (event.target === modal) close();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.classList.contains("hidden")) close();
  });
})();
