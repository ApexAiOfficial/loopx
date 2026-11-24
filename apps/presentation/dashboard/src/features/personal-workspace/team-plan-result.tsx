import type { WorkspaceActionPreview } from "./personal-workspace-model";
import type { WorkspaceTranslate } from "./i18n";
import { teamPlanAppliedLine, teamPlanGapReason } from "./team-plan-preview";

/** Assignment receipt, with the original proposal available on demand. */
export function TeamPlanResult({ proposal, t }: { proposal: WorkspaceActionPreview; t: WorkspaceTranslate }) {
  const recovered = proposal.teamPlanOutcome?.kind === "already_present";
  return <section className="personal-proposal-card personal-team-plan-result">
    <h3>{teamPlanAppliedLine(proposal.teamPlanOutcome ?? null, t)}</h3>
    <dl className="personal-team-plan-assignments">
      {proposal.teamPlanAssignments?.map((lane) => <div key={lane.laneId}>
        <dt>{lane.agentId || lane.laneId}</dt><dd>{lane.task}</dd>
      </div>)}
      {proposal.teamPlanGapLanes?.map((gap) => <div className="is-pending" key={gap.laneId}>
        <dt>{gap.agentId || gap.laneId}</dt>
        <dd>{gap.task || gap.laneId}<br /><small>{t("proposal.teamPlan.pending")} · {teamPlanGapReason(gap.reasonCode, t)}</small></dd>
      </div>)}
    </dl>
    <p>{t(recovered ? "proposal.teamPlan.recoveredHint" : "proposal.teamPlan.assignedHint")}</p>
    <details>
      <summary>{t("proposal.teamPlan.originalPlan")}</summary>
      <dl>{proposal.fields.map((field) => <div key={field.key}><dt>{field.label}</dt><dd>{field.value}</dd></div>)}</dl>
    </details>
  </section>;
}
