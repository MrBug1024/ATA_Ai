import type { BBox } from "@/lib/types/knowledge-graph";

// MinerU/OCR 的 bbox 归一化到 0–1000 网格（x 相对页宽、y 相对页高，各自按比例）。
// 反归一化：真实坐标 = 归一化值 / 1000 × 渲染尺寸。原点左上、y 向下，与图像空间一致，无需翻转 y。
const NORM_GRID = 1000;

interface BboxOverlayProps {
  bboxes: BBox[];
  /** 媒体渲染后的实际像素宽 */
  containerWidth: number;
  /** 媒体渲染后的实际像素高 */
  containerHeight: number;
  /** 归一化网格，默认 1000 */
  grid?: number;
}

export function BboxOverlay({
  bboxes,
  containerWidth,
  containerHeight,
  grid = NORM_GRID,
}: BboxOverlayProps) {
  const scaleX = containerWidth / grid;
  const scaleY = containerHeight / grid;

  return (
    <>
      {bboxes.map((b, i) => (
        <div
          key={i}
          data-bbox
          className="pointer-events-none absolute rounded-sm border border-blue-500 bg-blue-400/20"
          style={{
            left: b.x * scaleX,
            top: b.y * scaleY,
            width: b.w * scaleX,
            height: b.h * scaleY,
          }}
        />
      ))}
    </>
  );
}
