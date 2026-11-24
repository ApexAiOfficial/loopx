import { verifyWorkspaceLocales } from "../../apps/presentation/dashboard/smoke/workspace-locale-browser-smoke.mjs";
import { installApi, outputDir } from "./fixture.mjs";

export const workspaceLocaleScenario = {
  id: "workspace-locale",
  async run({ browser, url }) {
    await verifyWorkspaceLocales({ browser, url, installApi, outputDir });
    return { coverageEntries: [], note: "First-use browser language, saved choice, storage fallback, Settings, and mobile layout passed" };
  },
};
