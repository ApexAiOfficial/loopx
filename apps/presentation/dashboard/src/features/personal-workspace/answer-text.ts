/** Keep the saved-answer reader and the original conversation's visible text aligned. */
export const MIN_SEPARATE_ANSWER_LENGTH = 160;

export function visibleAgentMessage(value: string) {
  return value
    .split(/\r?\n/u)
    .filter((line) => !/^\s*GOAL_(STATUS|PROGRESS)\s*:/u.test(line))
    .map((line) => {
      if (/^\s*GOAL_EVIDENCE\s*:/u.test(line)) return line.replace(/^\s*GOAL_EVIDENCE\s*:/u, "验证依据：");
      if (/^\s*NEXT_ACTION\s*:/u.test(line)) return line.replace(/^\s*NEXT_ACTION\s*:/u, "下一步：");
      return line;
    })
    .join("\n")
    .trim();
}
