const presentation = document.querySelector('#presentation');
presentation.hidden = false;
document.querySelector('.stage-buttons').hidden = false;
presentation.addEventListener('click', () => {
  const enabled = document.body.classList.toggle('presenting');
  presentation.setAttribute('aria-pressed', String(enabled));
  presentation.textContent = enabled ? 'Reading mode' : 'Presentation mode';
});
const states = {
  pending: ['GitHub reports that checks are pending for the current revision.','Record the pull request, revision, and check state; an unchanged observation does not create progress.','Preserve the monitor and recovery condition, then wait for the result.','Admit work by authority, budget, and eligibility; work outside the wait scope can still proceed.','Stay quiet when nothing material changed, so polling does not become nagging.'],
  failed: ['CI failed on the current revision.','Distinguish a code regression, an environment failure, and an unknown cause; preserve the evidence.','Propose a bounded repair successor with a clear acceptance method.','Recheck the actor, write scope, and budget; execute only after eligibility is established.','Turn the failure into work someone can take over, not merely an error message.'],
  changed: ['The pull request changed from revision A to revision B.','The original review and tests are bound to A and cannot establish that B qualifies.','Reconfirm the change and validation scope; repeat review when needed.','Preserve version lineage and current authority; an old receipt cannot stand in for a new result.','Keep every “pass” attached to an unambiguous deliverable.'],
  merged: ['GitHub confirms that the pull request was merged.','Record the terminal state and result; a merge does not automatically complete the whole goal.','Check goal acceptance: add integration validation, continue with a successor, or explain why no successor is needed.','Settle the current monitor and successor; publication and other actions still require their own authority.','Give every piece of work an explicit destination, and do not keep searching for work by inertia after completion.']
};
document.querySelectorAll('[data-state]').forEach(button => button.addEventListener('click', () => {
  document.querySelectorAll('[data-state]').forEach(b => b.setAttribute('aria-pressed',String(b === button)));
  ['fact','domain','proposal','kernel','meaning'].forEach((id,i) => document.getElementById(id).textContent = states[button.dataset.state][i]);
}));
document.addEventListener('keydown', event => {
  if (!document.body.classList.contains('presenting') || event.altKey || event.ctrlKey || event.metaKey) return;
  if (event.key === 'Escape') { presentation.click(); return; }
  if (event.target.closest('input,textarea,select,[contenteditable=true]')) return;
  if (!['ArrowRight','ArrowLeft'].includes(event.key)) return;
  const sections = [...document.querySelectorAll('article > section')];
  let index = sections.findIndex(s => s.getBoundingClientRect().bottom > 100);
  index = Math.max(0, Math.min(sections.length - 1, index + (event.key === 'ArrowRight' ? 1 : -1)));
  event.preventDefault(); sections[index].scrollIntoView({behavior: 'instant'}); history.replaceState(null,'','#'+sections[index].id);
});
