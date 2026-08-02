"""compute_metrics 节点：确定性数值引擎，落 heavy payload，供报告段消费。

接在 fetch_full_context 之后、报告生成之前（见 docs/design/01-确定性数值引擎.md §8）。
纯计算、不抛错：数据缺失输出带标记的尽力结果，报告链路照常跑。
"""

from ..context_loader import resolve_full_context_data
from ..heavy_state import put_heavy_payload
from ..metrics_engine import compute_metrics
from ..state import AuditGraphState


def compute_metrics_node(state: AuditGraphState) -> AuditGraphState:
    """Compute deterministic metrics and stash them out-of-band."""
    data = resolve_full_context_data(state)
    metrics = compute_metrics(data)
    return {"computed_metrics_ref": put_heavy_payload("computed_metrics", metrics)}
