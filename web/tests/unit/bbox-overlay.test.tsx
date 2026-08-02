// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";

describe("BboxOverlay", () => {
  it("renders one div per bbox", async () => {
    const { BboxOverlay } = await import("@/components/knowledge-graph/bbox-overlay");
    const bboxes = [
      { x: 0, y: 0, w: 100, h: 20 },
      { x: 50, y: 30, w: 80, h: 15 },
    ];
    const { container } = render(
      <BboxOverlay bboxes={bboxes} containerWidth={400} containerHeight={550} />
    );
    const overlays = container.querySelectorAll("[data-bbox]");
    expect(overlays).toHaveLength(2);
  });

  it("按 0-1000 归一化网格 1:1 映射到等尺寸容器", async () => {
    const { BboxOverlay } = await import("@/components/knowledge-graph/bbox-overlay");
    const bboxes = [{ x: 124, y: 606, w: 749, h: 164 }];
    const { container } = render(
      <BboxOverlay bboxes={bboxes} containerWidth={1000} containerHeight={1000} />
    );
    const el = container.querySelector("[data-bbox]") as HTMLElement;
    expect(el.style.left).toBe("124px");
    expect(el.style.top).toBe("606px");
    expect(el.style.width).toBe("749px");
    expect(el.style.height).toBe("164px");
  });

  it("容器缩放时按 值/1000×尺寸 换算（x 用宽、y 用高）", async () => {
    const { BboxOverlay } = await import("@/components/knowledge-graph/bbox-overlay");
    const bboxes = [{ x: 500, y: 500, w: 200, h: 100 }];
    const { container } = render(
      <BboxOverlay bboxes={bboxes} containerWidth={500} containerHeight={800} />
    );
    const el = container.querySelector("[data-bbox]") as HTMLElement;
    expect(el.style.left).toBe("250px"); // 500/1000*500
    expect(el.style.top).toBe("400px"); // 500/1000*800
    expect(el.style.width).toBe("100px"); // 200/1000*500
    expect(el.style.height).toBe("80px"); // 100/1000*800
  });

  it("renders nothing for empty bbox list", async () => {
    const { BboxOverlay } = await import("@/components/knowledge-graph/bbox-overlay");
    const { container } = render(
      <BboxOverlay bboxes={[]} containerWidth={400} containerHeight={550} />
    );
    expect(container.querySelectorAll("[data-bbox]")).toHaveLength(0);
  });
});
