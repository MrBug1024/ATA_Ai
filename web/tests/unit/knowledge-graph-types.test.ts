import { describe, it, expectTypeOf } from "vitest";
import type {
  BBox,
  EvidenceItem,
  GraphNode,
  EvolutionItem,
  ValidationResponse,
} from "@/lib/types/knowledge-graph";

describe("knowledge-graph types", () => {
  it("BBox has x y w h as numbers", () => {
    expectTypeOf<BBox>().toEqualTypeOf<{
      x: number; y: number; w: number; h: number;
    }>();
  });

  it("EvidenceItem.chunk_id is string, file_id is number", () => {
    expectTypeOf<EvidenceItem["chunk_id"]>().toBeString();
    expectTypeOf<EvidenceItem["file_id"]>().toBeNumber();
  });

  it("GraphNode.risk_level follows the optional OpenAPI field", () => {
    expectTypeOf<GraphNode["risk_level"]>().toEqualTypeOf<string | null | undefined>();
  });

  it("EvolutionItem.action is ADD or OVERRIDE", () => {
    expectTypeOf<EvolutionItem["action"]>().toEqualTypeOf<"ADD" | "OVERRIDE">();
  });

  it("ValidationResponse.ready is boolean", () => {
    expectTypeOf<ValidationResponse["ready"]>().toBeBoolean();
  });
});
