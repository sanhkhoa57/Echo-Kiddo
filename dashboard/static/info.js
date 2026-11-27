(() => {
  let active;
  let pinned = false;
  let closeTimer;

  function close() {
    clearTimeout(closeTimer);
    if (!active) return;
    active.hidePopover?.();
    active.hidden = true;
    active = null;
    pinned = false;
  }

  function open(trigger, popup) {
    clearTimeout(closeTimer);
    if (active === popup) return;
    close();
    active = popup;
    popup.hidden = false;
    popup.showPopover?.();

    const anchor = trigger.getBoundingClientRect();
    const {width, height} = popup.getBoundingClientRect();
    const edge = 8;
    const left = Math.max(edge, Math.min(anchor.left + (anchor.width - width) / 2, document.documentElement.clientWidth - width - edge));
    const below = anchor.bottom + 5;
    const top = below + height <= innerHeight - edge ? below : Math.max(edge, anchor.top - height - 5);
    popup.style.left = left + "px";
    popup.style.top = top + "px";
  }

  for (const trigger of document.querySelectorAll("[data-info]")) {
    const popup = document.getElementById(trigger.dataset.info);
    let keyboardFocus = false;
    const scheduleClose = () => {
      if (active === popup && !pinned && !keyboardFocus) closeTimer = setTimeout(close, 160);
    };
    trigger.addEventListener("pointerenter", event => {
      if (event.pointerType === "mouse" || event.pointerType === "pen") open(trigger, popup);
    });
    trigger.addEventListener("pointerleave", scheduleClose);
    popup.addEventListener("pointerenter", () => clearTimeout(closeTimer));
    popup.addEventListener("pointerleave", scheduleClose);
    trigger.addEventListener("focus", () => {
      keyboardFocus = trigger.matches(":focus-visible");
      if (keyboardFocus) open(trigger, popup);
    });
    trigger.addEventListener("blur", () => {
      keyboardFocus = false;
      scheduleClose();
    });
    trigger.addEventListener("click", () => {
      if (active === popup && pinned) close();
      else {
        open(trigger, popup);
        pinned = true;
      }
    });
  }

  document.addEventListener("pointerdown", event => {
    if (active && !active.parentElement.contains(event.target)) close();
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && active) {
      event.preventDefault();
      close();
    }
  });
  window.addEventListener("scroll", close, {passive: true});
  window.addEventListener("resize", close);
})();
