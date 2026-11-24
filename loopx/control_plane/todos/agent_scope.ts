/** Shared read addressing; visibility never grants mutation or execution. */
export interface GateScope {
  global: boolean;
  blocks: string | null;
  claim: string | null;
}

export function gateAddressesAgent(gate: GateScope, agent: string | null): boolean {
  if (gate.global) return true;
  if (gate.blocks) return gate.blocks === agent;
  return !gate.claim || gate.claim === agent;
}


export interface ActionScope {bound: string | null; claim: string | null}
export interface ClaimScope {claim: string | null; excluded: readonly string[]}

/** Explicit action binding wins; retained unbound actions use their claim. */
export function actionAddressesAgent(action: ActionScope, agent: string | null): boolean {
  const bound = action.bound ?? action.claim;
  return !agent || !bound || bound === agent;
}

/** Claim/exclusion address Agent work, not permission to disregard User gates. */
export function claimAllowsAgent(work: ClaimScope, agent: string | null): boolean {
  return !agent || (!work.excluded.includes(agent) && (!work.claim || work.claim === agent));
}
