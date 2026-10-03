// Touch adaptations for nanoleaf.html inside the iPhone app. Runs after the page's script.
(function () {
  if (!window.NANO_IOS && !window.NANO_WEB) return;
  var $ = function (s) { return document.querySelector(s); };
  var haptic = function (s) { window.nanoHaptic && window.nanoHaptic(s); };

  // no pinch zoom; the layout is built for the phone
  var vp = document.querySelector('meta[name=viewport]');
  if (vp) vp.setAttribute("content", "width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover");

  // the Message pane sits outside the tabs card in the page markup; put it with the others
  var msg = $('[data-pane=message]'), scenes = $('[data-pane=scenes]');
  if (msg && scenes && msg.parentElement !== scenes.parentElement) scenes.parentElement.appendChild(msg);

  // ---------- bottom tab bar ----------
  var ICONS = {
    scenes: '<svg viewBox="0 0 24 24"><rect x="3.5" y="3.5" width="7" height="7" rx="2"/><rect x="13.5" y="3.5" width="7" height="7" rx="2"/><rect x="3.5" y="13.5" width="7" height="7" rx="2"/><rect x="13.5" y="13.5" width="7" height="7" rx="2"/></svg>',
    custom: '<svg viewBox="0 0 24 24"><path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2.2"/><circle cx="9" cy="17" r="2.2"/></svg>',
    colour: '<svg viewBox="0 0 24 24"><path d="M12 3.2s6.3 6.6 6.3 11.1a6.3 6.3 0 0 1-12.6 0C5.7 9.8 12 3.2 12 3.2z"/></svg>',
    paint: '<svg viewBox="0 0 24 24"><path d="M19.6 4.4a1.9 1.9 0 0 0-2.7 0l-7.6 7.6 2.7 2.7 7.6-7.6a1.9 1.9 0 0 0 0-2.7z"/><path d="M9.3 12a3.3 3.3 0 0 0-3.4 3.3c0 1.8-1.4 3.3-2.4 3.7 1.1.9 2.8 1.3 4.4 1.3a4.3 4.3 0 0 0 4.3-4.4"/></svg>',
    message: '<svg viewBox="0 0 24 24"><path d="M20 12.2c0 4-3.6 7.1-8 7.1-1.1 0-2.2-.2-3.1-.6L4 20l1.2-3.7C4.4 15.1 4 13.7 4 12.2 4 8.2 7.6 5 12 5s8 3.2 8 7.2z"/></svg>'
  };
  var tabs = $("#tabs");
  if (tabs) {
    tabs.classList.add("tabbar");
    tabs.querySelectorAll("button").forEach(function (b) {
      var label = b.textContent.trim();
      b.innerHTML = (ICONS[b.dataset.tab] || "") + "<span>" + label + "</span>";
      b.setAttribute("aria-label", label);
    });
    document.body.appendChild(tabs);
  }

  function markTab(t) {
    ["scenes", "custom", "colour", "paint", "message"].forEach(function (k) {
      document.documentElement.classList.toggle("tab-" + k, k === t);
    });
  }
  var origSetTab = window.setTab;
  if (typeof origSetTab === "function") {
    window.setTab = function (t, silent) {
      var changed = t !== tab;
      origSetTab(t, silent);
      markTab(t);
      if (changed && !silent) {
        haptic("select");
        // keep the wall in view while painting; otherwise start the new tab at the top of its content
        var target = t === "paint" ? $(".stage-card") : $("#tabs") && $("[data-pane=" + t + "]");
        if (target) {
          var top = target.getBoundingClientRect().top + window.scrollY - ($("header").offsetHeight + 12);
          if (t === "paint" || window.scrollY > top) window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
        }
      }
    };
    markTab(tab);
  }

  // ---------- pale scene colours: dark text on accent buttons so they stay readable ----------
  function lum(hex) {
    var m = /^#?([0-9a-f]{6})$/i.exec(String(hex).trim());
    if (!m) return 0;
    var n = parseInt(m[1], 16);
    return (0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255;
  }
  if (typeof renderHero === "function") {
    var origHero = window.renderHero;
    window.renderHero = function () {
      origHero.apply(this, arguments);
      var a1 = document.documentElement.style.getPropertyValue("--a1");
      document.documentElement.classList.toggle("light-accent", lum(a1) > 0.62);
    };
  }

  // ---------- paint by dragging a finger across the wall ----------
  var stage = $("#stage"), lastId = null;
  function panelAt(x, y) {
    var el = document.elementFromPoint(x, y);
    if (!el || typeof shapeEls === "undefined") return null;
    for (var id in shapeEls) if (shapeEls[id] === el) return el.classList.contains("ctrl-shape") ? null : +id;
    return null;
  }
  function paintAt(t) {
    var id = panelAt(t.clientX, t.clientY);
    if (id != null && id !== lastId) { lastId = id; paintPanel(id); haptic("light"); }
  }
  if (stage) {
    stage.addEventListener("touchstart", function (e) {
      if (tab !== "paint") return;
      e.preventDefault(); lastId = null; paintAt(e.touches[0]);
    }, { passive: false });
    stage.addEventListener("touchmove", function (e) {
      if (tab !== "paint") return;
      e.preventDefault(); paintAt(e.touches[0]);
    }, { passive: false });
  }

  // ---------- say "tap", not "click" ----------
  function retext(node) {
    if (node.nodeType === 3) {
      var v = node.nodeValue;
      if (/[Cc]lick/.test(v)) node.nodeValue = v.replace(/Click/g, "Tap").replace(/click/g, "tap");
    } else if (node.childNodes) {
      node.childNodes.forEach(retext);
    }
  }
  retext(document.body);
  new MutationObserver(function (list) {
    list.forEach(function (m) {
      if (m.type === "characterData") retext(m.target);
      m.addedNodes && m.addedNodes.forEach(retext);
    });
  }).observe(document.body, { subtree: true, childList: true, characterData: true });

  // ---------- haptics ----------
  document.addEventListener("click", function (e) {
    var t = e.target.closest && e.target.closest(".fav,.scene,.btn,.switch,.sw,.presets button,.cchip,.glyphs button,.icon-btn");
    if (!t || (t.disabled)) return;
    haptic(t.classList.contains("fav") || t.classList.contains("switch") ? "medium" : "light");
  }, true);
  if (typeof toast === "function") {
    var origToast = window.toast;
    window.toast = function (m, kind, ms) {
      if (kind === "err") haptic("error"); else if (kind === "warn") haptic("warning");
      return origToast(m, kind, ms);
    };
  }

  // Return in a single-line field closes the keyboard after its action runs
  document.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && e.target.matches("input.field")) setTimeout(function () { e.target.blur(); }, 0);
  });
})();
