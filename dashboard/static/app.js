/* EC - Echo Kiddo parent dashboard. Plain JavaScript, no dependencies. */
(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  for (const dropdown of $$("[data-dropdown]")) {
    const closeWhenOutside = (event) => {
      if (dropdown.open && !dropdown.contains(event.target)) dropdown.open = false;
    };
    document.addEventListener("click", closeWhenOutside);
    document.addEventListener("focusin", closeWhenOutside);
    dropdown.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || !dropdown.open) return;
      event.preventDefault();
      dropdown.open = false;
      dropdown.querySelector("summary").focus();
    });
  }

  /* ---------- Weekly chart: one readout, chosen by tap/click/keyboard; Escape hides a hover preview ---------- */
  const chartBars = $(".wchart-bars");
  if (chartBars) {
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") chartBars.classList.add("tips-dismissed"); });
    chartBars.addEventListener("pointerleave", () => chartBars.classList.remove("tips-dismissed"));
    $$(".wbar", chartBars).forEach((bar) => bar.addEventListener("pointerleave", () => chartBars.classList.remove("tips-dismissed")));
    chartBars.addEventListener("focusout", () => chartBars.classList.remove("tips-dismissed"));
    // On narrow phones the 44 px columns overflow: fade the cut edge and add a swipe hint, only while that is true.
    const weekCard = chartBars.closest(".area-week");
    const syncOverflow = () => {
      const over = chartBars.scrollWidth > chartBars.clientWidth + 1;
      weekCard.classList.toggle("is-overflow", over);
      weekCard.classList.toggle("at-end", !over || chartBars.scrollLeft + chartBars.clientWidth >= chartBars.scrollWidth - 2);
    };
    if (weekCard) {
      syncOverflow();
      chartBars.addEventListener("scroll", syncOverflow, { passive: true });
      window.addEventListener("resize", syncOverflow);
    }
  }
  $$(".wbar").forEach((bar) => bar.addEventListener("click", () => {
    const on = bar.getAttribute("aria-pressed") !== "true";
    $$(".wbar").forEach((b) => b.setAttribute("aria-pressed", "false"));
    bar.setAttribute("aria-pressed", on ? "true" : "false");
  }));

  /* ---------- First-paint entrance: after this, .home stops replaying it ---------- */
  const home = $(".home");
  if (home) setTimeout(() => home.setAttribute("data-entered", ""), 1200);

  const bootElement = $("#boot");
  if (!bootElement) return;
  const boot = JSON.parse(bootElement.textContent);
  const DAYS = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "CN"];
  const CATEGORIES = boot.categoryLabels || {};
  const BUDGET_KEYS = ["education", "entertainment", "social", "gaming", "unclassified"];

  function icon(name) {
    return `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  }

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k === "html") node.innerHTML = v;
      else if (v !== null && v !== undefined && v !== false) node.setAttribute(k, v === true ? "" : v);
    });
    (children || []).forEach((c) => node.append(c));
    return node;
  }

  function toast(message, kind) {
    const box = $("#toasts");
    const item = el("div", { class: "toast", "data-kind": kind || "ok", html: icon(kind === "error" ? "alert" : "check") });
    item.append(el("span", { text: message }));
    box.append(item);
    // Count down only while the page is visible, so a toast is never missed in a background tab
    let left = kind === "error" ? 7000 : 4000;
    let last = Date.now();
    const timer = setInterval(() => {
      const now = Date.now();
      if (!document.hidden) left -= now - last;
      last = now;
      if (left > 0) return;
      clearInterval(timer);
      item.setAttribute("data-leaving", "");
      item.addEventListener("transitionend", () => item.remove(), { once: true });
      setTimeout(() => item.remove(), 300); // reduced motion / no transition fallback
    }, 250);
  }

  async function api(method, url, body) {
    let resp;
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), 15000);
    try {
      resp = await fetch(url, {
        method,
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": boot.csrfToken },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: abort.signal,
      });
    } catch (e) {
      clearTimeout(timer);
      throw new Error(e.name === "AbortError"
        ? "Máy chủ không phản hồi sau 15 giây. Chưa rõ yêu cầu đã được ghi nhận hay chưa, hãy tải lại trang để kiểm tra."
        : "Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.");
    }
    let data = null;
    try {
      data = await resp.json();
    } catch (e) {
      if (e.name === "AbortError") { clearTimeout(timer); throw new Error("Máy chủ không phản hồi sau 15 giây. Chưa rõ yêu cầu đã được ghi nhận hay chưa, hãy tải lại trang để kiểm tra."); }
      /* empty body */
    } finally {
      clearTimeout(timer);
    }
    if (!resp.ok) {
      if (resp.status === 401) throw new Error("Phiên đăng nhập đã hết hạn. Tải lại trang để đăng nhập lại.");
      const detail = data && data.detail;
      throw new Error(typeof detail === "string" ? detail : "Máy chủ từ chối yêu cầu (mã " + resp.status + ").");
    }
    return data;
  }

  async function withBusy(button, task) {
    button.classList.add("is-busy");
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    try { return await task(); }
    finally {
      button.classList.remove("is-busy");
      button.removeAttribute("aria-busy");
      button.disabled = false;
    }
  }

  function confirmDialog(title, text, okLabel, destructive = false) {
    const dialog = $("#confirmDialog");
    if (!dialog || !dialog.showModal) return Promise.resolve(window.confirm(title + "\n\n" + text));
    $("#confirmTitle").textContent = title;
    $("#confirmText").textContent = text;
    const ok = $("#confirmOk");
    const cancel = $("#confirmCancel");
    ok.textContent = okLabel;
    ok.classList.toggle("btn-danger", destructive);
    dialog.showModal();
    cancel.focus();
    return new Promise((resolve) => {
      const done = (value) => {
        dialog.close();
        ok.onclick = cancel.onclick = dialog.oncancel = null;
        resolve(value);
      };
      ok.onclick = () => done(true);
      cancel.onclick = () => done(false);
      dialog.oncancel = (e) => { e.preventDefault(); done(false); };
    });
  }

  /* ---------- Child profile (works with or without a selected child) ---------- */
  const childForm = $("#childForm");
  if (childForm) {
    childForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const name = $("#childName").value.trim();
      const error = $("#childError");
      error.hidden = true;
      if (!name) {
        error.textContent = "Nhập tên gọi của con.";
        error.hidden = false;
        $("#childName").focus();
        return;
      }
      try {
        const child = await withBusy(childForm.querySelector("button"), () =>
          api("POST", "/api/v1/children", { display_name: name, age_group: $("#childAge").value }));
        window.location.href = "/dashboard?child_id=" + encodeURIComponent(child.id);
      } catch (err) {
        error.textContent = err.message;
        error.hidden = false;
      }
    });
  }

  if (!boot.childId) return;
  const CHILD = boot.childId;

  /* ---------- Tabs ---------- */
  const tabs = $$(".tab");
  const savebar = $("#savebar");
  let pending = false;
  const placeToasts = () => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => {
      pending = false;
      const bar = savebar.getBoundingClientRect();
      const clearance = bar.height ? Math.max(0, window.innerHeight - bar.top) : 0;
      $("#toasts").style.setProperty("--savebar-clearance", clearance + "px");
    });
  };
  const observer = new ResizeObserver(placeToasts);
  observer.observe(savebar);
  observer.observe(savebar.parentElement);
  window.addEventListener("scroll", placeToasts, { passive: true });
  window.addEventListener("resize", placeToasts);

  function setSavebarVisible(visible) {
    savebar.inert = !visible;
    savebar.hidden = !visible;
  }
  const calm = matchMedia("(prefers-reduced-motion: reduce)");

  // One sliding highlight behind the active rail item (vertical rail on desktop, bottom bar on phones).
  const tabList = $(".rail .tabs");
  let glider = null;
  if (tabList) {
    glider = el("span", { class: "rail-glider", "aria-hidden": "true" });
    tabList.prepend(glider);
    tabList.classList.add("has-glider");
  }
  function moveGlider(instant) {
    const active = tabs.find((t) => t.getAttribute("aria-selected") === "true");
    if (!glider || !active || !active.offsetWidth) return;
    if (instant) glider.style.transition = "none";
    glider.style.width = active.offsetWidth + "px";
    glider.style.height = active.offsetHeight + "px";
    glider.style.transform = `translate(${active.offsetLeft}px, ${active.offsetTop}px)`;
    if (instant) { void glider.offsetWidth; glider.style.transition = ""; }
  }
  if (tabList) new ResizeObserver(() => moveGlider(true)).observe(tabList);

  const phoneBar = matchMedia("(max-width: 720px)");
  const railVertical = () => !phoneBar.matches;
  function syncOrientation() { if (tabList) tabList.setAttribute("aria-orientation", railVertical() ? "vertical" : "horizontal"); }
  syncOrientation();
  phoneBar.addEventListener("change", syncOrientation);

  let firstShow = true;
  function showTab(name, focus, instant) {
    tabs.forEach((tab) => {
      const on = tab.dataset.tab === name;
      const panel = $("#panel-" + tab.dataset.tab);
      const wasHidden = panel.hidden;
      tab.setAttribute("aria-selected", on ? "true" : "false");
      tab.tabIndex = on ? 0 : -1;
      panel.hidden = !on;
      if (!on) panel.classList.remove("is-entering");
      // A short settle for the panel that just appeared; never on first paint, which has its own entrance.
      // Keyboard switches (focus === true) are instant: they repeat too often to animate.
      if (on && wasHidden && !firstShow && !focus && !instant && !calm.matches) {
        panel.classList.remove("is-entering");
        void panel.offsetWidth;
        panel.classList.add("is-entering");
        panel.addEventListener("animationend", () => panel.classList.remove("is-entering"), { once: true });
      }
      if (on && focus) tab.focus();
    });
    moveGlider(firstShow || Boolean(focus) || Boolean(instant));
    firstShow = false;
    setSavebarVisible(name === "schedule" || name === "rules" || isDirty());
    history.replaceState(null, "", "#" + name);
  }
  tabs.forEach((tab, i) => {
    // e.detail === 0 means Enter/Space activated the button: take the instant path.
    tab.addEventListener("click", (e) => showTab(tab.dataset.tab, e.detail === 0));
    tab.addEventListener("keydown", (e) => {
      const destinations = {
        ArrowLeft: (i + tabs.length - 1) % tabs.length,
        ArrowRight: (i + 1) % tabs.length,
        Home: 0,
        End: tabs.length - 1,
      };
      if (railVertical()) { destinations.ArrowUp = destinations.ArrowLeft; destinations.ArrowDown = destinations.ArrowRight; delete destinations.ArrowLeft; delete destinations.ArrowRight; }
      if (!Object.hasOwn(destinations, e.key)) return;
      e.preventDefault();
      showTab(tabs[destinations[e.key]].dataset.tab, true);
    });
  });

  /* ---------- Policy state ---------- */
  const saved = JSON.parse(JSON.stringify(boot.policy));
  let draft = JSON.parse(JSON.stringify(boot.policy));
  let slots = draft.schedule_matrix_7x48.split("");

  function isDirty() {
    draft.schedule_matrix_7x48 = slots.join("");
    return JSON.stringify(draft) !== JSON.stringify(saved);
  }
  function refreshSavebar() {
    const dirty = isDirty();
    savebar.dataset.dirty = dirty ? "true" : "false";
    $("#saveBtn").disabled = !dirty || $("#saveBtn").classList.contains("is-busy");
    $("#saveStatus").textContent = dirty
      ? "Có thay đổi chưa lưu."
      : "Quy định đang ở phiên bản " + saved.version + ".";
    const active = (tabs.find((t) => t.getAttribute("aria-selected") === "true") || {}).dataset;
    setSavebarVisible(dirty || Boolean(active && (active.tab === "schedule" || active.tab === "rules")));
  }
  window.addEventListener("beforeunload", (e) => {
    if (isDirty()) { e.preventDefault(); e.returnValue = ""; }
  });

  /* ---------- Limits ---------- */
  function bindLimit(id, key) {
    const input = $("#" + id);
    input.value = draft[key];
    input.addEventListener("input", () => {
      const value = parseInt(input.value, 10);
      const valid = Number.isInteger(value) && value >= 0 && value <= 1440;
      input.setAttribute("aria-invalid", valid ? "false" : "true");
      if (valid) draft[key] = value;
      refreshSavebar();
    });
  }
  bindLimit("weekdayLimit", "daily_limit_weekday_min");
  bindLimit("weekendLimit", "daily_limit_weekend_min");

  /* ---------- Schedule matrix ---------- */
  let activeDay = (new Date().getDay() + 6) % 7;
  let painting = null; // "0" | "1" while a drag is in progress

  function slotLabel(day, slot) {
    const h = String(Math.floor(slot / 2)).padStart(2, "0");
    const m = slot % 2 ? "30" : "00";
    return `${DAYS[day]} ${h}:${m}, ${slots[day * 48 + slot] === "1" ? "được dùng máy" : "khóa"}`;
  }
  function paintSlot(button) {
    const idx = Number(button.dataset.idx);
    const on = slots[idx] === "1";
    button.className = "slot " + (on ? "slot-on" : "slot-off");
    button.setAttribute("aria-pressed", on ? "true" : "false");
    button.setAttribute("aria-label", slotLabel(Math.floor(idx / 48), idx % 48));
  }
  function repaintAll() {
    $$(".slot[data-idx]").forEach(paintSlot);
    refreshSavebar();
  }
  function setSlot(idx, value) {
    if (slots[idx] === value) return;
    slots[idx] = value;
    $$(`.slot[data-idx="${idx}"]`).forEach(paintSlot);
    refreshSavebar();
  }
  function makeSlot(idx) {
    const button = el("button", { type: "button", "data-idx": idx, tabindex: "-1" });
    paintSlot(button);
    return button;
  }
  function bindPainting(container) {
    container.addEventListener("pointerdown", (e) => {
      const button = e.target.closest(".slot");
      if (!button || e.button !== 0 || !e.isPrimary) return;
      painting = slots[Number(button.dataset.idx)] === "1" ? "0" : "1";
      setSlot(Number(button.dataset.idx), painting);
      e.preventDefault();
      button.focus();
    });
    container.addEventListener("pointermove", (e) => {
      if (painting === null) return;
      const target = document.elementFromPoint(e.clientX, e.clientY);
      const button = target && target.closest ? target.closest(".slot") : null;
      if (button && container.contains(button)) setSlot(Number(button.dataset.idx), painting);
    });
    container.addEventListener("keydown", (e) => {
      const button = e.target.closest(".slot");
      if (!button) return;
      const idx = Number(button.dataset.idx);
      if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        setSlot(idx, slots[idx] === "1" ? "0" : "1");
        return;
      }
      const cols = Number(container.dataset.cols);
      const move = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: cols, ArrowUp: -cols }[e.key];
      if (!move) return;
      e.preventDefault();
      const next = $(`.slot[data-idx="${idx + move}"]`, container);
      if (next) { button.tabIndex = -1; next.tabIndex = 0; next.focus(); }
    });
  }
  window.addEventListener("pointerup", () => { painting = null; });
  window.addEventListener("pointercancel", () => { painting = null; });
  window.addEventListener("blur", () => { painting = null; });

  function buildMatrix() {
    const grid = $("#matrix");
    grid.dataset.cols = "48";
    grid.append(el("div"));
    for (let h = 0; h < 24; h++) grid.append(el("div", { class: "matrix-hour", text: h + "h" }));
    for (let day = 0; day < 7; day++) {
      grid.append(el("div", { class: "matrix-day" + (day >= 5 ? " is-weekend" : ""), text: DAYS[day] }));
      for (let slot = 0; slot < 48; slot++) grid.append(makeSlot(day * 48 + slot));
    }
    const first = $(".slot", grid);
    if (first) first.tabIndex = 0;
    bindPainting(grid);
  }
  function buildDayView() {
    const chips = $("#dayChips");
    DAYS.forEach((label, day) => {
      const chip = el("button", { type: "button", class: "day-chip" + (day >= 5 ? " is-weekend" : ""), text: label });
      chip.addEventListener("click", () => { activeDay = day; renderDayGrid(); });
      chips.append(chip);
    });
    const grid = $("#dayGrid");
    grid.dataset.cols = "6";
    bindPainting(grid);
    renderDayGrid();
  }
  function renderDayGrid() {
    $$("#dayChips .day-chip").forEach((chip, day) => chip.setAttribute("aria-pressed", day === activeDay ? "true" : "false"));
    const grid = $("#dayGrid");
    grid.textContent = "";
    for (let row = 0; row < 8; row++) {
      grid.append(el("div", { class: "daygrid-hour", text: String(row * 3).padStart(2, "0") + "h" }));
      for (let col = 0; col < 6; col++) grid.append(makeSlot(activeDay * 48 + row * 6 + col));
    }
    const first = $(".slot", grid);
    if (first) first.tabIndex = 0;
  }
  $("#copyDay").addEventListener("click", () => {
    const source = slots.slice(activeDay * 48, activeDay * 48 + 48);
    for (let day = 0; day < 7; day++) source.forEach((v, slot) => { slots[day * 48 + slot] = v; });
    repaintAll();
    toast("Đã áp dụng lịch " + DAYS[activeDay] + " cho cả tuần. Nhớ bấm Lưu quy định.");
  });
  $$("[data-preset]").forEach((button) => button.addEventListener("click", () => {
    for (let idx = 0; idx < 336; idx++) {
      const slot = idx % 48;
      if (button.dataset.preset === "all") slots[idx] = "1";
      else if (button.dataset.preset === "night") slots[idx] = slot >= 44 || slot < 12 ? "0" : "1";
      else slots[idx] = slot >= 34 && slot < 41 ? "1" : "0";
    }
    repaintAll();
  }));

  /* ---------- Category budgets ---------- */
  function renderBudgets() {
    const list = $("#budgetList");
    list.textContent = "";
    BUDGET_KEYS.forEach((key) => {
      const current = Object.prototype.hasOwnProperty.call(draft.category_budgets, key) ? draft.category_budgets[key] : -1;
      const mode = current < 0 ? "unlimited" : current === 0 ? "blocked" : "limited";
      const select = el("select", { class: "select", "aria-label": "Cách tính cho nhóm " + CATEGORIES[key] });
      [["unlimited", "Không giới hạn"], ["limited", "Giới hạn phút"], ["blocked", "Chặn hẳn"]].forEach(([value, label]) => {
        select.append(el("option", { value, text: label, selected: value === mode }));
      });
      const minutes = el("input", { type: "number", class: "input input-num", min: "1", max: "1440", step: "5", inputmode: "numeric", value: current > 0 ? current : 45, "aria-label": "Số phút cho nhóm " + CATEGORIES[key], hidden: mode !== "limited" });
      const apply = () => {
        minutes.hidden = select.value !== "limited";
        const value = parseInt(minutes.value, 10);
        const valid = Number.isInteger(value) && value >= 1 && value <= 1440;
        minutes.setAttribute("aria-invalid", valid ? "false" : "true");
        draft.category_budgets[key] = select.value === "unlimited" ? -1 : select.value === "blocked" ? 0 : (valid ? value : 45);
        refreshSavebar();
      };
      select.addEventListener("change", apply);
      minutes.addEventListener("input", apply);
      list.append(el("div", { class: "budget-row cat-" + key }, [
        el("span", { html: `<i class="swatch"></i>` + CATEGORIES[key] }),
        el("div", { class: "budget-controls" }, [select, minutes]),
      ]));
    });
  }

  /* ---------- App and domain rules ---------- */
  function fillCategories(select, fallback) {
    Object.entries(CATEGORIES).forEach(([value, label]) => select.append(el("option", { value, text: label, selected: value === fallback })));
  }
  fillCategories($("#appCategory"), "gaming");
  fillCategories($("#domainCategory"), "unclassified");

  function actionToggle(rule, name) {
    const group = el("div", { class: "seg", role: "group", "aria-label": "Hành động cho " + name });
    const groupName = "act-" + name + "-" + Math.random().toString(36).slice(2);
    [["allow", "Cho phép"], ["block", "Chặn"]].forEach(([value, label]) => {
      const input = el("input", { type: "radio", name: groupName, value, checked: rule.action === value });
      input.addEventListener("change", () => { rule.action = value; refreshSavebar(); });
      group.append(el("label", {}, [input, el("span", { text: label })]));
    });
    return group;
  }
  function ruleItem(rule, name, meta, onRemove) {
    const remove = el("button", { type: "button", class: "btn btn-sm btn-quiet btn-icon", "aria-label": "Xóa quy tắc " + name, html: icon("trash") });
    remove.addEventListener("click", onRemove);
    return el("li", { class: "rule-item" }, [
      el("div", {}, [el("div", { class: "rule-name", text: name }), el("div", { class: "rule-meta", text: meta })]),
      actionToggle(rule, name),
      remove,
    ]);
  }
  function emptyItem(text) {
    return el("li", { class: "rule-item" }, [el("div", { class: "rule-meta", text })]);
  }
  function renderApps() {
    const list = $("#appList");
    list.textContent = "";
    draft.app_rules.forEach((rule, i) => {
      const meta = (CATEGORIES[rule.category] || rule.category) + (rule.sha256 ? " · SHA-256 " + rule.sha256.slice(0, 12) + "…" : " · chỉ theo tên tệp");
      list.append(ruleItem(rule, rule.exe_name, meta, () => { draft.app_rules.splice(i, 1); renderApps(); refreshSavebar(); }));
    });
    if (!draft.app_rules.length) list.append(emptyItem("Chưa có quy tắc ứng dụng nào. Ứng dụng không có trong danh sách được coi là chưa phân loại."));
    $("#appCount").textContent = draft.app_rules.length + " quy tắc";
  }
  function renderDomains() {
    const list = $("#domainList");
    const filter = $("#domainFilter").value.trim().toLowerCase();
    list.textContent = "";
    let shown = 0;
    draft.domain_rules.forEach((rule, i) => {
      if (filter && !rule.domain.toLowerCase().includes(filter)) return;
      shown++;
      list.append(ruleItem(rule, rule.domain, CATEGORIES[rule.category] || rule.category, () => { draft.domain_rules.splice(i, 1); renderDomains(); refreshSavebar(); }));
    });
    if (!shown) list.append(emptyItem(filter ? "Không có tên miền nào khớp \"" + filter + "\"." : "Chưa có quy tắc tên miền nào."));
    $("#domainCount").textContent = draft.domain_rules.length + " quy tắc";
  }
  function fail(errorNode, input, message) {
    errorNode.textContent = message;
    errorNode.hidden = false;
    input.setAttribute("aria-invalid", "true");
    input.focus();
  }
  $("#appForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const nameInput = $("#appName"), hashInput = $("#appHash"), error = $("#appError");
    error.hidden = true;
    [nameInput, hashInput].forEach((i) => i.setAttribute("aria-invalid", "false"));
    const name = nameInput.value.trim().toLowerCase();
    const hash = hashInput.value.trim().toLowerCase();
    if (!/^[\w\-. ]+\.exe$/.test(name)) return fail(error, nameInput, "Nhập tên tệp chạy kết thúc bằng .exe, không kèm đường dẫn. Ví dụ: game.exe");
    if (hash && !/^[0-9a-f]{64}$/.test(hash)) return fail(error, hashInput, "SHA-256 phải gồm đúng 64 ký tự 0-9 và a-f.");
    if (draft.app_rules.some((r) => r.exe_name.toLowerCase() === name && (r.sha256 || "") === hash)) return fail(error, nameInput, "Quy tắc cho " + name + " đã có trong danh sách.");
    const rule = { exe_name: name, category: $("#appCategory").value, action: $("input[name=appAction]:checked").value };
    if (hash) rule.sha256 = hash;
    draft.app_rules.unshift(rule);
    nameInput.value = hashInput.value = "";
    renderApps();
    refreshSavebar();
  });
  $("#domainForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = $("#domainName"), error = $("#domainError");
    error.hidden = true;
    input.setAttribute("aria-invalid", "false");
    const domain = input.value.trim().toLowerCase().replace(/^https?:\/\//, "").replace(/\/.*$/, "").replace(/^www\./, "");
    if (!/^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$/.test(domain)) return fail(error, input, "Nhập tên miền hợp lệ, không kèm đường dẫn. Ví dụ: example.com");
    if (draft.domain_rules.some((r) => r.domain.toLowerCase() === domain)) return fail(error, input, domain + " đã có trong danh sách.");
    draft.domain_rules.unshift({ domain, category: $("#domainCategory").value, action: $("input[name=domainAction]:checked").value });
    input.value = "";
    $("#domainFilter").value = "";
    renderDomains();
    refreshSavebar();
  });
  $("#domainFilter").addEventListener("input", renderDomains);

  /* ---------- Save / discard ---------- */
  $("#saveBtn").addEventListener("click", async () => {
    if ($$("#panel-schedule [aria-invalid=true]").length) {
      toast("Có ô số phút chưa hợp lệ. Sửa rồi lưu lại.", "error");
      return;
    }
    draft.schedule_matrix_7x48 = slots.join("");
    const payload = JSON.parse(JSON.stringify({
      daily_limit_weekday_min: draft.daily_limit_weekday_min,
      daily_limit_weekend_min: draft.daily_limit_weekend_min,
      schedule_matrix_7x48: draft.schedule_matrix_7x48,
      category_budgets: draft.category_budgets,
      app_rules: draft.app_rules,
      domain_rules: draft.domain_rules,
    }));
    try {
      const result = await withBusy($("#saveBtn"), () => api("PUT", "/api/v1/policy/" + CHILD, payload));
      Object.assign(saved, payload, { version: result.version });
      draft.version = result.version;
      toast("Đã lưu phiên bản " + result.version + ". Máy của con nhận trong vòng 60 giây.");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      refreshSavebar();
    }
  });
  $("#discardBtn").addEventListener("click", () => {
    draft = JSON.parse(JSON.stringify(saved));
    slots = draft.schedule_matrix_7x48.split("");
    $("#weekdayLimit").value = draft.daily_limit_weekday_min;
    $("#weekendLimit").value = draft.daily_limit_weekend_min;
    $$("#panel-schedule [aria-invalid=true]").forEach((i) => i.setAttribute("aria-invalid", "false"));
    renderBudgets(); renderApps(); renderDomains(); repaintAll();
  });

  /* ---------- Urgent commands ---------- */
  // The server answers DISPATCHED whether or not a device is connected, so the wording says what is known.
  const COMMAND_NAME = {
    LOCK_NOW: "khóa máy",
    UNLOCK: "mở khóa",
    ADD_TIME_15M: "cộng thêm 15 phút",
    PARENT_PAUSE_2H: "tạm nghỉ kiểm soát 2 giờ",
  };
  const guardCard = $(".guard");
  const liveDevices = guardCard ? Number(guardCard.dataset.live || 0) : 0;
  const allDevices = guardCard ? Number(guardCard.dataset.total || 0) : 0;
  function commandSentText(command) {
    // What is known: the server accepted the command; how many machines had a live channel at page load.
    return "Máy chủ đã nhận lệnh " + COMMAND_NAME[command] + ". Khi tải trang, " + liveDevices + "/" + allDevices + " máy có kênh lệnh khẩn.";
  }
  // One urgent command at a time: the whole group is guarded from confirmation to response,
  // with aria-disabled so the button that started it keeps keyboard focus.
  const commandButtons = $$("[data-command]");
  let commandBusy = false;
  function setCommandsBusy(busy, active) {
    commandBusy = busy;
    commandButtons.forEach((b) => { if (busy) b.setAttribute("aria-disabled", "true"); else b.removeAttribute("aria-disabled"); });
    if (active) {
      active.classList.toggle("is-busy", busy);
      if (busy) active.setAttribute("aria-busy", "true"); else active.removeAttribute("aria-busy");
    }
  }
  commandButtons.forEach((button) => button.addEventListener("click", async () => {
    if (commandBusy) return;
    const command = button.dataset.command;
    setCommandsBusy(true, null);
    try {
      if (command === "PARENT_PAUSE_2H") {
        const ok = await confirmDialog("Tạm nghỉ kiểm soát 2 giờ?", "Lệnh áp dụng cho mọi thiết bị đã ghép của " + boot.childName + ". Từ lúc mỗi máy nhận lệnh, trong 2 giờ máy đó không bị giới hạn thời gian, ứng dụng hay trang web. Việc này được ghi vào nhật ký.", "Tạm nghỉ 2 giờ");
        if (!ok) return;
      }
      setCommandsBusy(true, button);
      await api("POST", "/api/v1/commands", {
        child_id: CHILD, command, params: button.dataset.params ? JSON.parse(button.dataset.params) : {},
      });
      toast(commandSentText(command));
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setCommandsBusy(false, button);
    }
  }));

  /* ---------- Child requests ----------
     Rows are reconciled by request_key, so polling never rebuilds a row that is still pending:
     focus, in-flight state and the entrance of genuinely new rows all survive the 20 s refresh. */
  const requestList = $("#requestList");
  const requestStatus = $("#requestStatus");
  const deciding = new Set();  // approve/deny call in flight
  const resolved = new Set();  // decided here; hidden until the server stops listing it
  const childName = boot.childName || "";
  let firstRequestRender = true;

  const deviceNames = JSON.parse(($("#deviceNames") || {}).textContent || "{}");
  function requestWhen(r) {
    const d = r.ts ? new Date(r.ts) : null;
    if (!d || isNaN(d)) return r.local_time;
    const pad = (n) => String(n).padStart(2, "0");
    const time = pad(d.getHours()) + ":" + pad(d.getMinutes());
    return d.toDateString() === new Date().toDateString() ? time : pad(d.getDate()) + "/" + pad(d.getMonth() + 1) + " " + time;
  }
  // The pairing list may have changed in another session: re-read it from the dashboard before approving.
  async function currentDeviceNames() {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);
    try {
      const resp = await fetch("/dashboard?child_id=" + encodeURIComponent(CHILD), { credentials: "same-origin", signal: ctrl.signal });
      if (!resp.ok) return null;
      const doc = new DOMParser().parseFromString(await resp.text(), "text/html");
      const node = doc.getElementById("deviceNames");
      return node ? JSON.parse(node.textContent) : null;
    } catch (e) { return null; }
    finally { clearTimeout(timer); }
  }
  let confirming = false; // one approval confirmation at a time
  async function verifySource(r) {
    const fresh = await currentDeviceNames();
    if (fresh && fresh[r.device_id]) return true;
    if (confirming) return false;
    confirming = true;
    try {
      const reason = fresh ? "Máy gửi yêu cầu này không còn được ghép." : "Chưa kiểm tra được máy gửi yêu cầu còn được ghép hay không.";
      return await confirmDialog("Duyệt cho mọi máy còn lại?", reason + " Lệnh cộng " + r.minutes + " phút có thể tới mọi máy còn lại của " + childName + ".", "Duyệt cho mọi máy");
    } finally { confirming = false; }
  }
  function requestRow(r) {
    const source = deviceNames[r.device_id] || "Máy đã gỡ";
    const when = requestWhen(r);
    const what = "yêu cầu xin thêm " + r.minutes + " phút lúc " + when + " từ " + source;
    const approve = el("button", { class: "btn btn-sm", html: icon("check") + "Duyệt", "aria-label": "Duyệt " + what });
    const deny = el("button", { class: "btn btn-sm btn-quiet", text: "Từ chối", "aria-label": "Từ chối " + what });
    // If the source machine is gone (or cannot be verified), the server grants time to every remaining device,
    // so approval re-checks pairing first, inside the row's pending state.
    approve.addEventListener("click", () => decide(r.request_key, "approve", approve, () => verifySource(r)));
    deny.addEventListener("click", () => decide(r.request_key, "deny", deny));
    // Pending rows use aria-disabled, not disabled, so a focused button keeps focus while the call runs.
    return el("div", { class: "req-row" + (firstRequestRender ? "" : " is-new"), "data-request": r.request_key }, [
      el("span", { class: "req-time num", text: when }),
      el("div", { class: "req-card" }, [
        el("span", { class: "req-avatar", "aria-hidden": "true", text: childName.slice(0, 1).toUpperCase() }),
        el("div", { class: "req-body" }, [
          el("span", { class: "request-what", text: "Xin thêm " + r.minutes + " phút" }),
          el("span", { class: "req-sub", text: source }),
        ]),
        el("div", { class: "req-actions" }, [approve, deny]),
      ]),
    ]);
  }
  function setRowBusy(row, busy) {
    $$("button", row).forEach((b) => { if (busy) b.setAttribute("aria-disabled", "true"); else b.removeAttribute("aria-disabled"); });
  }
  function renderRequests(all) {
    const requests = all.filter((r) => !resolved.has(r.request_key));
    const keys = new Set(requests.map((r) => r.request_key));
    resolved.forEach((k) => { if (!all.some((r) => r.request_key === k)) resolved.delete(k); });
    $("#requestCount").textContent = requests.length;
    $("#requestCount").hidden = requests.length === 0;
    const big = $("#pendingBig");
    if (big) big.textContent = requests.length;
    $("#pendingEmpty").hidden = requests.length > 0;
    $("#pendingLabel").hidden = requests.length === 0;

    // Remove rows that are gone, remembering where focus should land.
    let lostFocusAt = -1;
    $$(".req-row", requestList).forEach((row, index) => {
      if (keys.has(row.dataset.request)) return;
      if (row.contains(document.activeElement)) lostFocusAt = index;
      row.remove();
    });
    // Insert new rows in server order; existing nodes are moved, never rebuilt.
    let cursor = null;
    requests.forEach((r) => {
      let row = $(`.req-row[data-request="${CSS.escape(r.request_key)}"]`, requestList);
      if (!row) row = requestRow(r);
      setRowBusy(row, deciding.has(r.request_key));
      const want = cursor ? cursor.nextElementSibling : requestList.firstElementChild;
      if (row !== want) requestList.insertBefore(row, want);
      cursor = row;
    });
    $("#pendingRequests").hidden = requests.length === 0;
    if (lostFocusAt >= 0) {
      const rows = $$(".req-row", requestList);
      const target = rows[Math.min(lostFocusAt, rows.length - 1)];
      (target ? $("button", target) : $("#requestSummary")).focus();
    }
  }
  async function decide(key, verb, button, precheck) {
    if (deciding.has(key) || button.getAttribute("aria-disabled") === "true") return;
    const row = button.closest(".req-row");
    deciding.add(key);
    setRowBusy(row, true);
    button.classList.add("is-busy");
    button.setAttribute("aria-busy", "true");
    try {
      if (precheck && !(await precheck())) return;
      const result = await api("POST", `/api/v1/requests/${CHILD}/${verb}`, { request_key: key });
      resolved.add(key);
      const minutes = Math.round(((result && result.bonus_seconds) || 900) / 60);
      const noTargets = result && Array.isArray(result.targets) && result.targets.length === 0;
      toast(verb !== "approve" ? "Đã từ chối yêu cầu."
        : noTargets ? "Đã ghi nhận duyệt. Không có thiết bị nào để gửi lệnh."
        : "Đã ghi nhận duyệt. Máy chủ đã xếp lệnh cộng " + minutes + " phút. Bấm Làm mới ở thẻ Hạn mức để xem số dư mới.");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      deciding.delete(key);
      button.classList.remove("is-busy");
      button.removeAttribute("aria-busy");
      if (!resolved.has(key)) setRowBusy(row, false);
    }
    renderRequests(lastRequests);
    pollRequests();
  }
  let lastRequests = boot.pendingRequests || [];
  let pollHealthy = true;
  function setPollState(ok) {
    if (ok === pollHealthy) return; // announce transitions only
    pollHealthy = ok;
    if (requestStatus) { requestStatus.textContent = ok ? "Tự cập nhật" : "Chưa cập nhật được"; requestStatus.classList.toggle("is-stale", !ok); }
    const kpi = $("#kpiRequestStatus");
    if (kpi) { kpi.hidden = ok; kpi.classList.toggle("is-stale-text", !ok); }
    const live = $("#requestLive");
    if (live) live.textContent = ok ? "Đã cập nhật lại danh sách yêu cầu." : "Không cập nhật được danh sách yêu cầu. Đang hiện số đã biết.";
  }
  let pollSeq = 0;
  async function pollRequests() {
    const seq = ++pollSeq;
    try {
      const data = await api("GET", "/api/v1/requests/" + CHILD);
      if (seq !== pollSeq) return; // a newer poll already answered
      lastRequests = data.pending_requests;
      renderRequests(lastRequests);
      setPollState(true);
    } catch (e) {
      if (seq !== pollSeq) return;
      setPollState(false); // keep the last known list, say it may be out of date; the next poll retries
    }
  }
  requestList.textContent = "";
  renderRequests(lastRequests);
  firstRequestRender = false;
  setInterval(() => { if (!document.hidden) pollRequests(); }, 20000);

  /* ---------- Pairing ---------- */
  const consent = $("#consent"), pairBtn = $("#pairBtn");
  let pairTimer = null;
  consent.addEventListener("change", () => { pairBtn.disabled = !consent.checked; });
  pairBtn.addEventListener("click", async () => {
    try {
      const data = await withBusy(pairBtn, () => api("POST", "/api/v1/enroll/code", { child_id: CHILD, consent_confirmed: true }));
      const code = data.code || data.pairing_code;
      $("#pairCode").textContent = code;
      $("#pairCommand").textContent = `python agent/service/win_service.py enroll --code ${code} --server ${window.location.origin}`;
      $("#pairResult").hidden = false;
      const expires = data.expires_at_utc ? new Date(data.expires_at_utc).getTime() : Date.now() + 600000;
      clearInterval(pairTimer);
      const tick = () => {
        const left = Math.max(0, Math.round((expires - Date.now()) / 1000));
        $("#pairCountdown").textContent = left ? `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}` : "đã hết hạn";
        if (!left) clearInterval(pairTimer);
      };
      tick();
      pairTimer = setInterval(tick, 1000);
    } catch (err) { toast(err.message, "error"); }
  });
  $("#copyPair").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("#pairCommand").textContent);
      toast("Đã sao chép lệnh ghép đôi.");
    } catch (e) { toast("Trình duyệt không cho sao chép. Hãy chọn và chép tay.", "error"); }
  });

  /* ---------- Devices and data ---------- */
  $$("[data-revoke]").forEach((button) => button.addEventListener("click", async () => {
    const ok = await confirmDialog("Gỡ thiết bị " + button.dataset.name + "?", "Thiết bị này sẽ không nhận quy định và không gửi dữ liệu nữa. Muốn dùng lại phải ghép đôi bằng mã mới.", "Gỡ thiết bị", true);
    if (!ok) return;
    try {
      await withBusy(button, () => api("POST", `/api/v1/devices/${button.dataset.revoke}/revoke`));
      window.location.reload();
    } catch (err) { toast(err.message, "error"); }
  }));
  $("#purgeBtn").addEventListener("click", async () => {
    const ok = await confirmDialog("Xóa toàn bộ dữ liệu hoạt động của " + boot.childName + "?", "Mọi sự kiện đã ghi trên máy chủ và trong bộ đệm trên máy của con sẽ bị xóa. Không khôi phục được.", "Xóa dữ liệu", true);
    if (!ok) return;
    try {
      const data = await withBusy($("#purgeBtn"), () => api("DELETE", `/api/v1/privacy/children/${CHILD}/events`));
      toast("Đã xóa " + data.deleted_count + " sự kiện.");
      setTimeout(() => window.location.reload(), 1200);
    } catch (err) { toast(err.message, "error"); }
  });
  $("#printBtn").addEventListener("click", () => { showTab("today", false, true); window.print(); });
  const reportDetails = $("#reportDetails");
  let reportWasOpen;
  window.addEventListener("beforeprint", () => {
    reportWasOpen = reportDetails.open;
    reportDetails.open = true;
  });
  window.addEventListener("afterprint", () => { reportDetails.open = reportWasOpen; });

  /* ---------- Quick actions: jump to a tab and focus the field ---------- */
  $$("[data-goto]").forEach((button) => button.addEventListener("click", (e) => {
    const keyboard = e.detail === 0;
    showTab(button.dataset.goto, false, keyboard);
    const target = button.dataset.focus && $(button.dataset.focus);
    if (target) {
      target.scrollIntoView({ block: "center", behavior: keyboard || calm.matches ? "auto" : "smooth" });
      target.focus({ preventScroll: true });
    }
  }));

  /* ---------- Init ---------- */
  buildMatrix();
  buildDayView();
  renderBudgets();
  renderApps();
  renderDomains();
  const initial = (window.location.hash || "").slice(1);
  showTab(tabs.some((t) => t.dataset.tab === initial) ? initial : "today");
  refreshSavebar();

  /* ---------- First-paint entrance: plays once per page load, never on later tab returns.
     Numbers are final from the first frame; only the containers and chart geometry settle in. ---------- */
  const loadedAt = $("#loadedAt");
  if (loadedAt) { const t = new Date(); loadedAt.textContent = String(t.getHours()).padStart(2, "0") + ":" + String(t.getMinutes()).padStart(2, "0"); }
  const refreshToday = $("#refreshToday");
  // Unsaved policy edits are already guarded by the beforeunload prompt.
  if (refreshToday) refreshToday.addEventListener("click", () => { history.replaceState(null, "", "#today"); location.reload(); });
})();
