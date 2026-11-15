/* Page-size chips + prev / page numbers / next. Sizes persist per list. */
import { store } from "../lib";

export function usePageSize(key: string, fallback: number) {
  const k = `pagesize.${key}`;
  return [store.get<number>(k, fallback), (n: number) => store.set(k, n)] as const;
}

export function PageSize({ value, options, onChange, total }: {
  value: number; options: number[]; onChange: (n: number) => void; total: number;
}) {
  return (
    <div className="pager-size" role="group" aria-label="Items per page">
      <span className="faint small">Show</span>
      {options.map((n) => (
        <button key={n} className="chip sm" aria-pressed={value === n} onClick={() => onChange(n)}>
          {n >= 9999 ? "All" : n}
        </button>
      ))}
      <span className="faint small">of {total}</span>
    </div>
  );
}

export function Pager({ page, pages, onPage }: { page: number; pages: number; onPage: (p: number) => void }) {
  if (pages <= 1) return null;
  const nums: (number | "…")[] = [];
  for (let i = 1; i <= pages; i++) {
    if (i === 1 || i === pages || Math.abs(i - page) <= 1) nums.push(i);
    else if (nums[nums.length - 1] !== "…") nums.push("…");
  }
  return (
    <nav className="pager" aria-label="Pages">
      <button className="chip sm" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page">‹ Prev</button>
      {nums.map((n, i) => n === "…"
        ? <span key={`e${i}`} className="faint">…</span>
        : <button key={n} className="chip sm" aria-pressed={n === page} aria-label={`Page ${n}`} onClick={() => onPage(n)}>{n}</button>)}
      <button className="chip sm" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page">Next ›</button>
    </nav>
  );
}
