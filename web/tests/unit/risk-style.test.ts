import { describe, it, expect } from "vitest";
import { scoreToRiskLevel, riskBadgeClass, RISK_BADGE_CLASS } from "@/lib/utils/risk-style";

describe("risk-style", () => {
  it("scoreToRiskLevel: ≥75 高、≥50 中、其余低", () => {
    expect(scoreToRiskLevel(75)).toBe("high");
    expect(scoreToRiskLevel(90)).toBe("high");
    expect(scoreToRiskLevel(50)).toBe("medium");
    expect(scoreToRiskLevel(74)).toBe("medium");
    expect(scoreToRiskLevel(49)).toBe("low");
    expect(scoreToRiskLevel(0)).toBe("low");
  });

  it("riskBadgeClass: 已知等级取对应色,未知归 unknown", () => {
    expect(riskBadgeClass("high")).toBe(RISK_BADGE_CLASS.high);
    expect(riskBadgeClass("low")).toBe(RISK_BADGE_CLASS.low);
    expect(riskBadgeClass("nonsense")).toBe(RISK_BADGE_CLASS.unknown);
  });
});
