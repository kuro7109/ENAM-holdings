/* Press feedback for the whole app.
   - Ripple from the touch point on pointerdown (instant, visual).
   - Haptic on click, not pointerdown: Chrome only allows navigator.vibrate after the tap has
     completed (user activation), so vibrating on pointerdown silently fails on the first tap.
   - iPhone Safari has no vibrate(); on iOS 18+ toggling a native <input switch> produces a real
     system haptic, so we keep a hidden one and click its label inside the tap handler. */
const TAPPABLE = "button, .btn, .chip, a.linkbtn";

const canVibrate = typeof navigator !== "undefined" && typeof navigator.vibrate === "function";
let iosLabel: HTMLLabelElement | null = null;

function iosHaptic() {
  if (!iosLabel) {
    const input = document.createElement("input");
    input.type = "checkbox";
    input.setAttribute("switch", "");
    input.id = "finn-haptic";
    input.tabIndex = -1;
    input.setAttribute("aria-hidden", "true");
    iosLabel = document.createElement("label");
    iosLabel.htmlFor = "finn-haptic";
    iosLabel.setAttribute("aria-hidden", "true");
    const box = document.createElement("div");
    box.style.cssText = "position:fixed;width:1px;height:1px;overflow:hidden;opacity:0;pointer-events:none;left:-9px;top:0";
    box.append(input, iosLabel);
    document.body.appendChild(box);
  }
  iosLabel.click();
}

export function buzz(ms: number) {
  try {
    if (canVibrate) navigator.vibrate(ms);
    else iosHaptic();
  } catch {
    /* unsupported: skip silently */
  }
}

let lastTick = 0;
/** Light, rate-limited tick for continuous controls (sliders). */
export function tick() {
  const now = performance.now();
  if (now - lastTick < 60) return;
  lastTick = now;
  buzz(3);
}

export function installPress() {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  document.addEventListener("pointerdown", (e) => {
    if (reduce) return;
    const el = (e.target as HTMLElement).closest<HTMLElement>(TAPPABLE);
    if (!el || (el as HTMLButtonElement).disabled) return;
    const r = el.getBoundingClientRect();
    const size = Math.max(r.width, r.height) * 2.2;
    const s = document.createElement("span");
    s.className = "ripple";
    s.style.cssText = `width:${size}px;height:${size}px;left:${e.clientX - r.left - size / 2}px;top:${e.clientY - r.top - size / 2}px`;
    el.appendChild(s);
    window.setTimeout(() => s.remove(), 600);
  }, { passive: true });

  document.addEventListener("click", (e) => {
    const el = (e.target as HTMLElement).closest<HTMLElement>(TAPPABLE);
    if (!el || (el as HTMLButtonElement).disabled || el.closest("label[for='finn-haptic']")) return;
    if (el.matches(".done")) return; // Done has its own, firmer success haptic
    buzz(el.matches(".btn") ? 8 : 4);
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
