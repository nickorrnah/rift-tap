/**
 * overlay.js
 *
 * Connects to the Python server's WebSocket, listens for card scan events,
 * and drives the card panel animation.
 *
 * Concepts worth knowing:
 *
 *  WebSocket  — a persistent, two-way connection over TCP.  Unlike a regular
 *               HTTP request (ask → answer → done), the WebSocket stays open
 *               so the server can push events at any time.
 *
 *  Reconnection — network glitches or server restarts will close the socket.
 *                 Exponential back-off means the first retry is fast but
 *                 subsequent retries slow down so we don't spam the server.
 */

(function () {
  "use strict";

  // ── Configuration ──────────────────────────────────────────────────────────
  // Derive the WebSocket URL from the page's own hostname/port so the overlay
  // works without changes whether it's on localhost or the Pi's IP address.
  // wss:// is required when the page is served over https:// (e.g. via ngrok).
  const WS_PROTOCOL = location.protocol === "https:" ? "wss:" : "ws:";
  const WS_URL = `${WS_PROTOCOL}//${location.host}/ws`;

  // Images are served from the /images/ path on the same server.
  const IMAGE_BASE = `http://${location.host}/images/`;

  // Fall-back image shown when the card has no image on disk yet.
  const PLACEHOLDER_IMAGE = `http://${location.host}/images/placeholder.svg`;

  // ── DOM references ─────────────────────────────────────────────────────────
  const panel      = document.getElementById("card-panel");
  const imgEl      = document.getElementById("card-image");
  const nameEl     = document.getElementById("card-name");
  const metaEl     = document.getElementById("card-meta");
  const rulesEl    = document.getElementById("card-rules");
  const statusDot  = document.getElementById("status-dot");

  // ── State ──────────────────────────────────────────────────────────────────
  let hideTimer     = null;   // setTimeout handle for auto-hiding the card
  let retryDelay    = 1000;   // ms before the next reconnect attempt
  const MAX_DELAY   = 30000;  // cap retries at 30 s
  let showCardInfo  = false;  // mirrors server overlay_settings.show_card_info
  // ── WebSocket ──────────────────────────────────────────────────────────────
  function connect() {
    const ws = new WebSocket(WS_URL);

    ws.addEventListener("open", () => {
      console.log("[overlay] WebSocket connected");
      statusDot.className = "connected";
      retryDelay = 1000;  // reset back-off on successful connection
    });

    ws.addEventListener("message", (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch (e) {
        console.warn("[overlay] Non-JSON message:", event.data);
        return;
      }
      handleMessage(msg);
    });

    ws.addEventListener("close", () => {
      console.warn(`[overlay] WebSocket closed — retrying in ${retryDelay / 1000}s`);
      statusDot.className = "disconnected";
      setTimeout(connect, retryDelay);
      retryDelay = Math.min(retryDelay * 2, MAX_DELAY);  // exponential back-off
    });

    ws.addEventListener("error", (e) => {
      console.error("[overlay] WebSocket error:", e);
    });
  }

  // ── Message handler ────────────────────────────────────────────────────────
  function handleMessage(msg) {
    if (msg.event === "card_scanned") {
      showCard(msg.card, msg.display_duration ?? 8);
    } else if (msg.event === "unknown_tag") {
      console.info("[overlay] Unknown tag:", msg.uid);
    } else if (msg.event === "settings") {
      applySettings(msg);
    }
  }

  // ── Settings ───────────────────────────────────────────────────────────────
  function applySettings(settings) {
    showCardInfo = !!settings.show_card_info;
    // Update the panel class immediately — works whether a card is visible or not.
    panel.classList.toggle("info-hidden", !showCardInfo);
  }

  // ── Card display ───────────────────────────────────────────────────────────
  function showCard(card, durationSeconds) {
    // Cancel any pending hide from the previous card.
    if (hideTimer !== null) {
      clearTimeout(hideTimer);
      hideTimer = null;
    }

    // Populate content.
    const imageSrc = card.image_filename
      ? IMAGE_BASE + card.image_filename
      : PLACEHOLDER_IMAGE;

    imgEl.src   = imageSrc;
    imgEl.alt   = card.name;
    nameEl.textContent  = card.name;

    const costStr  = card.cost != null ? `Cost ${card.cost}  ·  ` : "";
    const typeStr  = card.card_type || "";
    const traitStr = card.traits ? `  ·  ${card.traits}` : "";
    metaEl.textContent  = `${costStr}${typeStr}${traitStr}`;

    rulesEl.textContent = card.rules_text || "";

    // Make panel visible.
    panel.classList.remove("hidden");

    // A tiny setTimeout lets the browser finish the display:none→block
    // transition before we add .visible; without it the CSS transition
    // sometimes won't fire.
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        panel.classList.add("visible");
      });
    });

    // Schedule auto-hide.
    hideTimer = setTimeout(() => hideCard(), durationSeconds * 1000);
  }

  function hideCard() {
    panel.classList.remove("visible");

    // Wait for the CSS transition to finish before setting display:none.
    // The transition duration is 0.6 s (--transition-out); we wait 700 ms
    // to be safe.
    setTimeout(() => {
      panel.classList.add("hidden");
    }, 700);
  }

  // ── Boot ───────────────────────────────────────────────────────────────────
  connect();
})();
