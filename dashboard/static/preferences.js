(() => {
  "use strict";
  const root = document.documentElement;
  let theme = "light", language = "vi";
  try {
    if (localStorage.getItem("ogk-theme") === "dark") theme = "dark";
    if (localStorage.getItem("ogk-language") === "en") language = "en";
  } catch {}
  root.dataset.theme = theme;
  root.lang = language;

  var COMIC = {
    light: { line: '#34536a', a: '#80cfff', b: '#dce8f2', dot: 'rgba(62,148,202,.55)' },
    dark: { line: '#453958', a: '#ba9ae6', b: '#7edbc5', dot: 'rgba(186,154,230,.6)' }
  };
  // apply(): hàm đổi giao diện thật (chạy trong View Transition). palette: 'light' | 'dark'.
  function inkReveal(x, y, palette, apply, ms) {
    var cl = COMIC[palette], reach = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
    var maxR = reach + 190;                                        // đi hết cả dải vòng màu ra khỏi màn hình
    var maskStyle = document.createElement('style'), ink = null, running = true;
    // Giữ View Transition sống đủ ms (nhóm "root" chạy hoạt ảnh trống), nếu không nó kết thúc sau 0,25 giây mặc định.
    var keep = '::view-transition-group(root){animation-duration:' + (ms + 80) + 'ms;animation-timing-function:linear}'
      + '::view-transition-old(ink),::view-transition-new(ink){animation:none}'
      + '::view-transition-group(ink){animation:none}';
    var maskCss = function (v) { return keep + '::view-transition-new(root){-webkit-mask:' + v + ';mask:' + v + '}'; };
    var finish = function () { running = false; maskStyle.remove(); if (ink) ink.remove(); };
    function begin() {
      apply();
      maskStyle.textContent = maskCss('linear-gradient(transparent,transparent)');   // che kín ngay, không nháy giao diện mới
      document.head.appendChild(maskStyle);
      ink = document.createElement('div');
      ink.setAttribute('aria-hidden', 'true');
      ink.style.cssText = 'position:fixed;inset:0;z-index:1;pointer-events:none;view-transition-name:ink';
      ink.innerHTML = '<div style="position:absolute;inset:0"></div><div style="position:absolute;inset:0"></div>';
      document.body.insertBefore(ink, document.body.firstChild);
    }
    var vt = document.startViewTransition(begin);
    vt.finished.then(finish, finish);
    vt.ready.then(function () {
      var rings = ink.children[0], dots = ink.children[1], t0 = performance.now();
      var at = 'circle at ' + x + 'px ' + y + 'px';
      dots.style.backgroundImage = 'radial-gradient(circle,' + cl.dot + ' 2.2px,transparent 2.6px)';
      dots.style.backgroundSize = '11px 11px';
      (function frame(now) {
        if (!running) return;
        var p = Math.min(1, (now - t0) / ms);
        var e = p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
        var R = maxR * (0.25 * p + 0.75 * e);
        var g = function (v) { return Math.max(0, v).toFixed(1) + 'px'; };
        // Từ trong ra ngoài: [trống] viền mảnh | vòng b | viền mảnh | vòng a | viền đậm (đè lên mép lộ) | [trống]
        rings.style.background = 'radial-gradient(' + at + ',transparent ' + g(R - 61) + ','
          + cl.line + ' ' + g(R - 61) + ' ' + g(R - 57) + ',' + cl.b + ' ' + g(R - 57) + ' ' + g(R - 37) + ','
          + cl.line + ' ' + g(R - 37) + ' ' + g(R - 33) + ',' + cl.a + ' ' + g(R - 33) + ' ' + g(R - 4) + ','
          + cl.line + ' ' + g(R - 4) + ' ' + g(R + 3) + ',transparent ' + g(R + 3) + ')';
        var ring = 'radial-gradient(' + at + ',transparent ' + g(R - 190) + ',#000 ' + g(R - 190) + ' ' + g(R - 66) + ',transparent ' + g(R - 66) + ')';
        dots.style.webkitMask = dots.style.mask = ring;
        maskStyle.textContent = maskCss('radial-gradient(' + at + ',#000 ' + g(R) + ',transparent ' + g(R + 0.8) + ')');
        if (p < 1) requestAnimationFrame(frame);
      })(t0);
    }).catch(finish);
    return vt;
  }

  // ---------- sáng / tối ----------
  document.addEventListener("DOMContentLoaded", () => {
    const themeButton = document.querySelector("#themeBtn");
    const langButton = document.querySelector("#langBtn");
    let active;
    function sync() {
      root.dataset.theme = theme;
      root.lang = language;
      themeButton.setAttribute("aria-checked", String(theme === "dark"));
      themeButton.setAttribute("aria-label", language === "en" ? "Dark theme" : "Giao diện tối");
      langButton.dataset.lang = language;
      document.querySelector('meta[name="theme-color"]').content = theme === "dark" ? "#101923" : "#f5f6f8";
    }
    function change(button, key, apply) {
      if (active) return;
      const update = () => {
        apply();
        sync();
        try { localStorage.setItem("ogk-" + key, key === "theme" ? theme : language); } catch {}
      };
      if (!document.startViewTransition || matchMedia("(prefers-reduced-motion: reduce)").matches) {
        update();
        return;
      }
      const rect = button.getBoundingClientRect();
      const x = rect.left + rect.width / 2, y = rect.top + rect.height / 2;
      if (key === "language") {
        active = inkReveal(x, y, theme, update, 1600);
      } else {
        const radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
        active = document.startViewTransition(update);
        active.ready.then(() => root.animate({
          clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`]
        }, {duration: 1600, easing: "cubic-bezier(.45,0,.25,1)", pseudoElement: "::view-transition-new(root)"})).catch(() => {});
      }
      active.finished.finally(() => { active = null; langButton.classList.remove("moving"); });
    }
    themeButton.onclick = () => change(themeButton, "theme", () => { theme = theme === "light" ? "dark" : "light"; });
    langButton.onclick = () => change(langButton, "language", () => {
      language = language === "vi" ? "en" : "vi";
      langButton.classList.add("moving");
      window.setInterfaceLanguage(language);
    });
    sync();
    window.setInterfaceLanguage(language);
  });
})();
