/**
 * overlay.js — OBS Browser Source script for Rift Tap
 *
 * Connects to the Python server via WebSocket and drives card panel animations.
 * Uses a state machine (hidden / entering / visible / exiting) to coordinate
 * transitions cleanly regardless of when new scans arrive.
 */
(function () {
  "use strict";

  // ── Configuration ──────────────────────────────────────────────────────────
  const WS_PROTOCOL       = location.protocol === "https:" ? "wss:" : "ws:";
  const WS_URL            = `${WS_PROTOCOL}//${location.host}/ws`;
  const IMAGE_BASE        = `${location.protocol}//${location.host}/images/`;
  const PLACEHOLDER_IMAGE = `${location.protocol}//${location.host}/images/placeholder.svg`;

  // ── DOM references ─────────────────────────────────────────────────────────
  const panel     = document.getElementById("card-panel");
  const imgEl     = document.getElementById("card-image");
  const nameEl    = document.getElementById("card-name");
  const metaEl    = document.getElementById("card-meta");
  const rulesEl   = document.getElementById("card-rules");
  const statusDot = document.getElementById("status-dot");

  // ── State ──────────────────────────────────────────────────────────────────
  let hideTimer    = null;
  let retryDelay   = 1000;
  const MAX_DELAY  = 30000;
  let showCardInfo = false;
  let enterAnim    = "slide-right";
  let exitAnim     = "fade";
  let panelState   = "hidden"; // "hidden" | "entering" | "visible" | "exiting"

  // ── Animation maps ─────────────────────────────────────────────────────────
  const ENTER_MAP = {
    "fade":          { kf: "enter-fade",        dur: "0.4s",  ease: "ease-out" },
    "slide-right":   { kf: "enter-slide-right", dur: "0.4s",  ease: "ease-out" },
    "slide-left":    { kf: "enter-slide-left",  dur: "0.4s",  ease: "ease-out" },
    "slide-up":      { kf: "enter-slide-up",    dur: "0.4s",  ease: "ease-out" },
    "slide-down":    { kf: "enter-slide-down",  dur: "0.4s",  ease: "ease-out" },
    "zoom":          { kf: "enter-zoom",        dur: "0.35s", ease: "ease-out" },
    "slam":          { kf: "enter-slam",        dur: "0.55s", ease: "cubic-bezier(0.22,1,0.36,1)" },
    "bounce":        { kf: "enter-bounce",      dur: "0.65s", ease: "ease-out" },
    "elastic":       { kf: "enter-elastic",     dur: "0.65s", ease: "ease-out" },
    "flip-h":        { kf: "enter-flip-h",      dur: "0.4s",  ease: "ease-in-out" },
    "flip-v":        { kf: "enter-flip-v",      dur: "0.4s",  ease: "ease-in-out" },
    "rotate-tl-ccw": { kf: "enter-rotate-ccw",  dur: "0.45s", ease: "ease-out", origin: "0% 0%"    },
    "rotate-tl-cw":  { kf: "enter-rotate-cw",   dur: "0.45s", ease: "ease-out", origin: "0% 0%"    },
    "rotate-tr-cw":  { kf: "enter-rotate-cw",   dur: "0.45s", ease: "ease-out", origin: "100% 0%"  },
    "rotate-tr-ccw": { kf: "enter-rotate-ccw",  dur: "0.45s", ease: "ease-out", origin: "100% 0%"  },
    "rotate-bl-cw":  { kf: "enter-rotate-cw",   dur: "0.45s", ease: "ease-out", origin: "0% 100%"  },
    "rotate-bl-ccw": { kf: "enter-rotate-ccw",  dur: "0.45s", ease: "ease-out", origin: "0% 100%"  },
    "rotate-br-ccw": { kf: "enter-rotate-ccw",  dur: "0.45s", ease: "ease-out", origin: "100% 100%" },
    "rotate-br-cw":  { kf: "enter-rotate-cw",   dur: "0.45s", ease: "ease-out", origin: "100% 100%" },
  };

  const EXIT_MAP = {
    "fade":          { kf: "exit-fade",        dur: "0.4s",  ease: "ease-in" },
    "slide-right":   { kf: "exit-slide-right", dur: "0.4s",  ease: "ease-in" },
    "slide-left":    { kf: "exit-slide-left",  dur: "0.4s",  ease: "ease-in" },
    "slide-up":      { kf: "exit-slide-up",    dur: "0.4s",  ease: "ease-in" },
    "slide-down":    { kf: "exit-slide-down",  dur: "0.4s",  ease: "ease-in" },
    "zoom":          { kf: "exit-zoom",        dur: "0.35s", ease: "ease-in" },
    "slam":          { kf: "exit-slam",        dur: "0.45s", ease: "ease-in" },
    "bounce":        { kf: "exit-bounce",      dur: "0.45s", ease: "ease-in" },
    "elastic":       { kf: "exit-elastic",     dur: "0.4s",  ease: "ease-in" },
    "flip-h":        { kf: "exit-flip-h",      dur: "0.4s",  ease: "ease-in-out" },
    "flip-v":        { kf: "exit-flip-v",      dur: "0.4s",  ease: "ease-in-out" },
    "rotate-tl-ccw": { kf: "exit-rotate-ccw",  dur: "0.45s", ease: "ease-in", origin: "0% 0%"    },
    "rotate-tl-cw":  { kf: "exit-rotate-cw",   dur: "0.45s", ease: "ease-in", origin: "0% 0%"    },
    "rotate-tr-cw":  { kf: "exit-rotate-cw",   dur: "0.45s", ease: "ease-in", origin: "100% 0%"  },
    "rotate-tr-ccw": { kf: "exit-rotate-ccw",  dur: "0.45s", ease: "ease-in", origin: "100% 0%"  },
    "rotate-bl-cw":  { kf: "exit-rotate-cw",   dur: "0.45s", ease: "ease-in", origin: "0% 100%"  },
    "rotate-bl-ccw": { kf: "exit-rotate-ccw",  dur: "0.45s", ease: "ease-in", origin: "0% 100%"  },
    "rotate-br-ccw": { kf: "exit-rotate-ccw",  dur: "0.45s", ease: "ease-in", origin: "100% 100%" },
    "rotate-br-cw":  { kf: "exit-rotate-cw",   dur: "0.45s", ease: "ease-in", origin: "100% 100%" },
  };

  // ── WebSocket ──────────────────────────────────────────────────────────────
  function connect() {
    const ws = new WebSocket(WS_URL);

    ws.addEventListener("open", () => {
      console.log("[overlay] WebSocket connected");
      statusDot.className = "connected";
      retryDelay = 1000;
    });

    ws.addEventListener("message", (event) => {
      let msg;
      try { msg = JSON.parse(event.data); }
      catch (e) { console.warn("[overlay] Non-JSON message:", event.data); return; }
      handleMessage(msg);
    });

    ws.addEventListener("close", () => {
      console.warn("[overlay] WebSocket closed — retrying in " + (retryDelay / 1000) + "s");
      statusDot.className = "disconnected";
      setTimeout(connect, retryDelay);
      retryDelay = Math.min(retryDelay * 2, MAX_DELAY);
    });

    ws.addEventListener("error", function (e) {
      console.error("[overlay] WebSocket error:", e);
    });
  }

  // ── Message handler ────────────────────────────────────────────────────────
  function handleMessage(msg) {
    if (msg.event === "card_scanned") {
      showCard(msg.card, msg.display_duration != null ? msg.display_duration : 8);
    } else if (msg.event === "unknown_tag") {
      console.info("[overlay] Unknown tag:", msg.uid);
    } else if (msg.event === "settings") {
      applySettings(msg);
    }
  }

  // ── Settings ───────────────────────────────────────────────────────────────
  function applySettings(settings) {
    showCardInfo = !!settings.show_card_info;
    panel.classList.toggle("info-hidden", !showCardInfo);
    if (settings.show_status_dot !== undefined) {
      statusDot.style.display = settings.show_status_dot ? "block" : "none";
    }
    if (settings.entrance_animation) { enterAnim = settings.entrance_animation; }
    if (settings.exit_animation)     { exitAnim  = settings.exit_animation; }
  }

  // ── Animation helpers ──────────────────────────────────────────────────────
  function applyEnterCfg(cfg) {
    panel.style.setProperty("--enter-anim",   cfg.kf);
    panel.style.setProperty("--anim-dur-in",  cfg.dur);
    panel.style.setProperty("--anim-ease-in", cfg.ease);
    panel.style.transformOrigin = cfg.origin ? cfg.origin : "50% 50%";
  }

  function applyExitCfg(cfg) {
    panel.style.setProperty("--exit-anim",     cfg.kf);
    panel.style.setProperty("--anim-dur-out",  cfg.dur);
    panel.style.setProperty("--anim-ease-out", cfg.ease);
    panel.style.transformOrigin = cfg.origin ? cfg.origin : "50% 50%";
  }

  function populateContent(card) {
    imgEl.src = card.image_filename ? IMAGE_BASE + card.image_filename : PLACEHOLDER_IMAGE;
    imgEl.alt = card.name;
    nameEl.textContent = card.name;
    var costStr = card.cost != null ? ("Cost " + card.cost + "  \u00b7  ") : "";
    metaEl.textContent = costStr + (card.card_type || "") + (card.traits ? ("  \u00b7  " + card.traits) : "");
    rulesEl.textContent = card.rules_text || "";
  }

  function startEntrance(durationSeconds) {
    var cfg = ENTER_MAP[enterAnim] || ENTER_MAP["fade"];
    applyEnterCfg(cfg);
    panel.classList.remove("hidden");
    panelState = "entering";
    void panel.offsetWidth; // force reflow
    panel.classList.add("entering");
    panel.addEventListener("animationend", function () {
      panel.classList.remove("entering");
      panelState = "visible";
    }, { once: true });
    // Start the hide timer from the moment of the scan, not after the
    // entrance animation ends — gives the full configured duration every time.
    if (durationSeconds > 0) {
      hideTimer = setTimeout(hideCard, durationSeconds * 1000);
    }
  }

  function doSimultaneousSwitch(card, durationSeconds) {
    var clone = panel.cloneNode(true);
    // Keep the id so the clone inherits all #card-panel CSS rules
    // (position:fixed, dimensions, background, etc).
    // getElementById always returns the FIRST match, so the real panel
    // remains the one JS operates on.
    clone.classList.remove("entering", "exiting", "hidden");

    // Insert the clone BEFORE the real panel so the real panel (new card)
    // sits on top in the stacking order — later in DOM = higher z-order.
    panel.parentNode.insertBefore(clone, panel);

    // Apply the configured exit animation to the clone.
    var exitCfg = EXIT_MAP[exitAnim] || EXIT_MAP["fade"];
    clone.style.setProperty("--exit-anim",     exitCfg.kf);
    clone.style.setProperty("--anim-dur-out",  exitCfg.dur);
    clone.style.setProperty("--anim-ease-out", exitCfg.ease);
    clone.style.transformOrigin = exitCfg.origin || "50% 50%";
    void clone.offsetWidth;
    clone.classList.add("exiting");
    clone.addEventListener("animationend", function () {
      clone.remove();
    }, { once: true });

    populateContent(card);
    var enterCfg = ENTER_MAP[enterAnim] || ENTER_MAP["fade"];
    applyEnterCfg(enterCfg);
    panelState = "entering";
    void panel.offsetWidth;
    panel.classList.add("entering");
    panel.addEventListener("animationend", function () {
      panel.classList.remove("entering");
      panelState = "visible";
    }, { once: true });
    // Timer starts from the scan, not from when the entrance animation ends.
    if (durationSeconds > 0) {
      hideTimer = setTimeout(hideCard, durationSeconds * 1000);
    }
  }

  // ── Card display ───────────────────────────────────────────────────────────
  function showCard(card, durationSeconds) {
    if (hideTimer !== null) { clearTimeout(hideTimer); hideTimer = null; }

    if (panelState === "visible") {
      doSimultaneousSwitch(card, durationSeconds);
      return;
    }

    if (panelState === "entering" || panelState === "exiting") {
      panel.classList.remove("entering", "exiting");
      panelState = "hidden";
      void panel.offsetWidth;
    }

    populateContent(card);
    startEntrance(durationSeconds);
  }

  function hideCard() {
    hideTimer = null;
    if (panelState !== "visible") { return; }
    panelState = "exiting";
    var cfg = EXIT_MAP[exitAnim] || EXIT_MAP["fade"];
    applyExitCfg(cfg);
    panel.classList.remove("entering");
    void panel.offsetWidth;
    panel.classList.add("exiting");
    panel.addEventListener("animationend", function () {
      panel.classList.remove("exiting");
      panel.classList.add("hidden");
      panelState = "hidden";
      panel.style.transformOrigin = "";
    }, { once: true });
  }

  // ── Boot ───────────────────────────────────────────────────────────────────
  connect();

}());
