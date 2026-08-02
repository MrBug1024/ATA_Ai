"use client";

import { useCallback } from "react";
import type { ValidateDocCategoryReq, ValidateDocCategoryResp } from "@/lib/types/doc-categories";
import { validateDocCategory } from "@/lib/backend/cases";

export function useValidateDocCategory() {
  const validate = useCallback(
    (req: ValidateDocCategoryReq): Promise<ValidateDocCategoryResp> => validateDocCategory(req),
    []
  );

  return { validate };
}
