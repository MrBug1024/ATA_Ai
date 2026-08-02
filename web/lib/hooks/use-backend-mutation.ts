"use client";

import { useState, useCallback, useRef } from "react";

/**
 * 命令式后端操作的通用状态机:trigger 执行、data/error 暂存、reset 清空。
 * 各业务 hook 用它包装 lib/backend 操作,并以语义化名字(resolve/validate/fetch)暴露 trigger。
 */
export function useBackendMutation<TReq, TResp>(fn: (req: TReq) => Promise<TResp>) {
  const [data, setData] = useState<TResp | null>(null);
  const [isMutating, setIsMutating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fnRef = useRef(fn);
  const requestSequenceRef = useRef(0);
  fnRef.current = fn;

  const trigger = useCallback(async (req: TReq): Promise<TResp> => {
    const requestSequence = ++requestSequenceRef.current;
    setIsMutating(true);
    setError(null);
    try {
      const result = await fnRef.current(req);
      if (requestSequence === requestSequenceRef.current) {
        setData(result);
      }
      return result;
    } catch (err) {
      if (requestSequence === requestSequenceRef.current) {
        setError(err instanceof Error ? err.message : "Unknown error");
      }
      throw err;
    } finally {
      if (requestSequence === requestSequenceRef.current) {
        setIsMutating(false);
      }
    }
  }, []);

  const reset = useCallback(() => {
    requestSequenceRef.current += 1;
    setData(null);
    setError(null);
    setIsMutating(false);
  }, []);

  return { data, isMutating, error, trigger, reset };
}
