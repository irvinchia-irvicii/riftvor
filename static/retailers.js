"use strict";

const retailerForm = document.getElementById("retailer-form");
retailerForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = retailerForm.querySelector("button[type=submit]");
  const status = document.getElementById("retailer-status");
  button.disabled = true;
  status.textContent = "Saving your request…";
  try {
    const response = await fetch("/api/retailers/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        shop_name: retailerForm.elements.shop_name.value,
        email: retailerForm.elements.email.value,
        newsletter_consent: retailerForm.elements.newsletter_consent.checked,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "Could not save your request.");
    retailerForm.reset();
    status.textContent = data.message;
  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
