/* Soraka's Wish account modal + session state. */
"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const modal = $("auth-modal");
  if (!modal) return;

  let state = { authenticated: false, account: null };
  let pendingTarget = null;

  function setError(message = "") {
    const box = $("auth-error");
    box.textContent = message;
    box.classList.toggle("hidden", !message);
  }

  function setTab(mode) {
    const login = mode === "login";
    $("auth-login-tab").classList.toggle("active", login);
    $("auth-signup-tab").classList.toggle("active", !login);
    $("auth-login-form").classList.toggle("hidden", !login);
    $("auth-signup-form").classList.toggle("hidden", login);
    setError();
  }

  function render() {
    document.body.classList.toggle("has-account", state.authenticated);
    const hasPortfolio = Boolean(state.account?.entitlements?.portfolio_analytics);
    document.body.classList.toggle("has-portfolio", hasPortfolio);
    for (const btn of document.querySelectorAll("[data-account-button]")) {
      btn.textContent = state.authenticated
        ? state.account.email.split("@")[0] : "Sign in";
      btn.classList.toggle("signed-in", state.authenticated);
    }
    for (const el of document.querySelectorAll("[data-member-email]")) {
      el.textContent = state.account?.email || "";
    }
    for (const el of document.querySelectorAll("[data-portfolio-perk]")) {
      el.textContent = hasPortfolio
        ? "✓ Portfolio Analytics active" : "◇ Portfolio Analytics · locked";
      el.classList.toggle("locked", !hasPortfolio);
    }
    $("auth-guest-view").classList.toggle("hidden", state.authenticated);
    $("auth-member-view").classList.toggle("hidden", !state.authenticated);
  }

  function open(reason, target = null) {
    pendingTarget = target || pendingTarget;
    if (reason) $("auth-reason").textContent = reason;
    render();
    modal.classList.remove("hidden");
  }

  function close() {
    modal.classList.add("hidden");
    setError();
  }

  async function request(path, payload) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "Account request failed.");
    return data;
  }

  async function submit(form, mode) {
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    setError();
    try {
      const data = await request(`/api/auth/${mode}`, {
        email: form.elements.email.value,
        password: form.elements.password.value,
      });
      state = { authenticated: true, account: data.account };
      render();
      document.dispatchEvent(new CustomEvent("shopdiff:authchange", {
        detail: state,
      }));
      if (pendingTarget) {
        window.location.href = pendingTarget;
      } else {
        window.location.reload();
      }
    } catch (error) {
      setError(error.message);
    } finally {
      button.disabled = false;
    }
  }

  async function loadState() {
    try {
      const response = await fetch("/api/auth/me");
      state = await response.json();
    } catch {
      state = { authenticated: false, account: null };
    }
    render();

    const gate = new URLSearchParams(window.location.search).get("gate");
    if (!state.authenticated && gate === "collection") {
      open("Create a free account or sign in to open your private collection.",
           "/collection");
    }
    if (!state.authenticated && gate === "portfolio") {
      open("Sign in to check whether Portfolio Analytics is active for your account.",
           "/portfolio");
    }
    return state;
  }

  $("auth-login-tab").onclick = () => setTab("login");
  $("auth-signup-tab").onclick = () => setTab("signup");
  $("auth-close").onclick = close;
  $("auth-login-form").onsubmit = (event) => {
    event.preventDefault();
    submit(event.currentTarget, "login");
  };
  $("auth-signup-form").onsubmit = (event) => {
    event.preventDefault();
    submit(event.currentTarget, "signup");
  };
  $("auth-logout").onclick = async () => {
    await request("/api/auth/logout", {});
    window.location.href = "/";
  };
  modal.addEventListener("click", (event) => {
    if (event.target === modal) close();
  });

  for (const btn of document.querySelectorAll("[data-account-button]")) {
    btn.addEventListener("click", () => open());
  }
  for (const link of document.querySelectorAll("[data-member-link]")) {
    link.addEventListener("click", (event) => {
      if (state.authenticated) return;
      event.preventDefault();
      open("Create a free account or sign in to open your private collection.",
           link.getAttribute("href"));
    });
  }
  for (const link of document.querySelectorAll("[data-portfolio-link]")) {
    link.addEventListener("click", (event) => {
      if (state.account?.entitlements?.portfolio_analytics) return;
      event.preventDefault();
      if (!state.authenticated) {
        open("Sign in to open your portfolio preview.", link.getAttribute("href"));
      } else {
        window.location.href = "/collection?gate=portfolio";
      }
    });
  }

  window.ShopDiffAuth = {
    get state() { return state; },
    open,
    requireAccount(reason, target = null) { open(reason, target); },
  };
  window.ShopDiffAuth.ready = loadState();
})();
