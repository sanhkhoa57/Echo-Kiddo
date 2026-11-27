/* OGK parent dashboard. Plain JavaScript, no dependencies. */
(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  const kidSelect = $("#kidSelect");
  if (kidSelect) {
    kidSelect.addEventListener("change", () => {
      window.location.href = "/child-view?child_id=" + encodeURIComponent(kidSelect.value);
    });
  }

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
    try {
      resp = await fetch(url, {
        method,
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": boot.csrfToken },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (e) {
      throw new Error("Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.");
    }
    let data = null;
    try { data = await resp.json(); } catch (e) { /* empty body */ }
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

  const childSelect = $("#childSelect");
  if (childSelect) {
    childSelect.addEventListener("change", () => {
      window.location.href = "/dashboard?child_id=" + encodeURIComponent(childSelect.value);
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
  function showTab(name, focus) {
    tabs.forEach((tab) => {
      const on = tab.dataset.tab === name;
      tab.setAttribute("aria-selected", on ? "true" : "false");
      tab.tabIndex = on ? 0 : -1;
      $("#panel-" + tab.dataset.tab).hidden = !on;
      if (on && focus) tab.focus();
    });
    setSavebarVisible(name === "schedule" || name === "rules" || isDirty());
    history.replaceState(null, "", "#" + name);
  }
  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => showTab(tab.dataset.tab));
    tab.addEventListener("keydown", (e) => {
      const destinations = {
        ArrowLeft: (i + tabs.length - 1) % tabs.length,
        ArrowRight: (i + 1) % tabs.length,
        Home: 0,
        End: tabs.length - 1,
      };
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
  const COMMAND_TEXT = {
    LOCK_NOW: "Đã gửi lệnh khóa máy.",
    UNLOCK: "Đã gửi lệnh mở khóa.",
    ADD_TIME_15M: "Đã cộng thêm 15 phút.",
    PARENT_PAUSE_2H: "Đã tạm nghỉ kiểm soát trong 2 giờ.",
  };
  $$("[data-command]").forEach((button) => button.addEventListener("click", async () => {
    const command = button.dataset.command;
    if (command === "PARENT_PAUSE_2H") {
      const ok = await confirmDialog("Tạm nghỉ kiểm soát 2 giờ?", "Trong 2 giờ tới máy của con không bị giới hạn thời gian, ứng dụng hay trang web. Việc này được ghi vào nhật ký.", "Tạm nghỉ 2 giờ");
      if (!ok) return;
    }
    try {
      await withBusy(button, () => api("POST", "/api/v1/commands", {
        child_id: CHILD, command, params: button.dataset.params ? JSON.parse(button.dataset.params) : {},
      }));
      toast(COMMAND_TEXT[command]);
    } catch (err) { toast(err.message, "error"); }
  }));

  /* ---------- Child requests ---------- */
  function renderRequests(requests) {
    const list = $("#requestList");
    const count = $("#requestCount");
    count.textContent = requests.length;
    const big = $("#pendingBig");
    if (big) big.textContent = requests.length;
    count.hidden = requests.length === 0;
    list.textContent = "";
    if (!requests.length) {
      list.append(el("div", { class: "empty", html: "<strong>Không có yêu cầu nào đang chờ.</strong>Khi con bấm \"Xin thêm giờ\" trên máy, yêu cầu hiện ở đây để bố mẹ duyệt hoặc từ chối." }));
      return;
    }
    requests.forEach((r) => {
      const approve = el("button", { class: "btn btn-sm", html: icon("check") + "Duyệt +15 phút" });
      const deny = el("button", { class: "btn btn-sm btn-quiet", text: "Từ chối" });
      approve.addEventListener("click", () => decide(approve, r.request_key, "approve"));
      deny.addEventListener("click", () => decide(deny, r.request_key, "deny"));
      const what = el("div");
      what.append(el("span", { class: "request-what", text: "Con xin thêm " + r.minutes + " phút" }), " ", el("span", { class: "muted small", text: "lúc " + r.local_time }));
      list.append(el("div", { class: "request" }, [what, el("div", { class: "row" }, [approve, deny])]));
    });
  }
  async function decide(button, key, verb) {
    try {
      await withBusy(button, () => api("POST", `/api/v1/requests/${CHILD}/${verb}`, { request_key: key }));
      toast(verb === "approve" ? "Đã duyệt. Máy của con được cộng 15 phút." : "Đã từ chối yêu cầu.");
      await pollRequests();
    } catch (err) { toast(err.message, "error"); }
  }
  async function pollRequests() {
    try {
      const data = await api("GET", "/api/v1/requests/" + CHILD);
      renderRequests(data.pending_requests);
    } catch (e) { /* keep the last known list; the next poll retries */ }
  }
  renderRequests(boot.pendingRequests || []);
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
  $("#printBtn").addEventListener("click", () => { showTab("today"); window.print(); });

  /* ---------- Init ---------- */
  buildMatrix();
  buildDayView();
  renderBudgets();
  renderApps();
  renderDomains();
  const initial = (window.location.hash || "").slice(1);
  showTab(tabs.some((t) => t.dataset.tab === initial) ? initial : "today");
  refreshSavebar();
})();
