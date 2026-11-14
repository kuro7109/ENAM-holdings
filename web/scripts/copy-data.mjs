// Copies the backend's JSON into public/data so the app is self-contained on Vercel.
// Real data (../data/out) wins. If it's missing, sample data is copied and the app labels it.
import { cpSync, existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const real = join(web, "..", "data");
const dest = join(web, "public", "data");
rmSync(dest, { recursive: true, force: true });
mkdirSync(join(dest, "out"), { recursive: true });

const hasReal = existsSync(join(real, "out", "feed.json")) || existsSync(join(real, "out", "market.json"));
if (hasReal) {
  cpSync(join(real, "out"), join(dest, "out"), { recursive: true, filter: (s) => !s.endsWith(".gitkeep") });
  if (existsSync(join(real, "research"))) cpSync(join(real, "research"), join(dest, "research"), { recursive: true });
  console.log("data: using real data from ../data");
} else {
  const s = join(web, "sample");
  for (const f of ["market.json", "alerts.json", "signals.json", "feed.json"]) cpSync(join(s, f), join(dest, "out", f));
  cpSync(join(s, "research"), join(dest, "research"), { recursive: true });
  writeFileSync(join(dest, "SAMPLE"), "1");
  console.log("data: ../data/out is empty, using labelled SAMPLE data");
}
