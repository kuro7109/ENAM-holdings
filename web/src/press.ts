/* One passive listener gives every tappable thing a ripple from the touch point and a light
   haptic tick. Primary actions buzz a little more; "Done" gets a pop (see markDone). */
const TAPPABLE = "button, .btn, .chip, a.linkbtn";

function buzz(ms: number) {
  try { navigator.vibrate?.(ms); } catch { /* unsupported: skip silently */ }
}

export function installPress() {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  document.addEventListener("pointerdown", (e) => {
    const el = (e.target as HTMLElement).closest<HTMLElement>(TAPPABLE);
    if (!el || (el as HTMLButtonElement).disabled) return;
    buzz(el.matches(".btn, .done") ? 8 : 4);
    if (reduce) return;
    const r = el.getBoundingClientRect();
    const size = Math.max(r.width, r.height) * 2.2;
    const s = document.createElement("span");
    s.className = "ripple";
    s.style.cssText = `width:${size}px;height:${size}px;left:${e.clientX - r.left - size / 2}px;top:${e.clientY - r.top - size / 2}px`;
    el.appendChild(s);
    window.setTimeout(() => s.remove(), 600);
  }, { passive: true });
}

export function success(el?: Element | null) {
  buzz(15);
  if (el && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    el.classList.remove("pop");
    void (el as HTMLElement).offsetWidth;
    el.classList.add("pop");
  }
}
