// 风险等级 → 徽章样式的单一事实来源。
// 之前 cases 页 CompositeBadge(按分数)与图谱 relation-detail-panel(按等级)
// 各自硬编码同一套 destructive/amber/emerald 风险色,易漂移。

export type RiskLevel = "high" | "medium" | "low" | "unknown";

export const RISK_BADGE_CLASS: Record<RiskLevel, string> = {
  high: "text-destructive bg-destructive/10",
  medium: "text-amber-500 bg-amber-500/10",
  low: "text-emerald-500 bg-emerald-500/10",
  unknown: "text-muted-foreground bg-muted",
};

/** 综合风险分(0–100)映射到风险等级:≥75 高、≥50 中、其余低。 */
export function scoreToRiskLevel(score: number): RiskLevel {
  if (score >= 75) return "high";
  if (score >= 50) return "medium";
  return "low";
}

/** 等级字符串(可能为任意后端值)安全取风险色,未知归 unknown。 */
export function riskBadgeClass(level: string): string {
  return RISK_BADGE_CLASS[level as RiskLevel] ?? RISK_BADGE_CLASS.unknown;
}
