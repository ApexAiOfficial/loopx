// @ts-expect-error The smoke compiler intentionally runs without @types/node.
import { readFileSync, existsSync } from "node:fs";
function assert(value: boolean, message: string) { if (!value) throw new Error(message); }
const router = readFileSync("src/router.tsx", "utf8");
for (const route of ["/frontstage", "/frontstage/developer", "/deprecated/frontstage/ops", "/developers/projections"]) {
  assert(router.includes(`path: "${route}"`), `bookmark route missing: ${route}`);
}
for (const retired of ["frontstage-page.tsx", "deprecated/frontstage-ops-page.tsx", "deprecated/frontstage-ops.css"]) {
  assert(!existsSync(`src/views/${retired}`), `retired UI still ships: ${retired}`);
}
assert(!router.includes("DeprecatedFrontstageOpsPage"), "old Ops board must not be mounted");
const publicRedirect = router.slice(router.indexOf("function PublicCasesRedirect"), router.indexOf("function WorkspaceRedirect"));
assert(!/statusUrl|goalId|fetch\(/.test(publicRedirect), "public migration must not consume local state");
assert(router.includes("resolveLocalStatusUrl"), "Ops migration must retain the existing source boundary");
assert(router.includes('to="/" search={{ goalId, statusUrl }}'), "Ops bookmarks must retain the selected Goal and source");
const developer = readFileSync("src/views/frontstage-developer-page.tsx", "utf8");
assert(!/fetch\(|useQuery\(/.test(developer), "contributor tools must not load live state");
console.log("frontstage retirement route contract: ok");
