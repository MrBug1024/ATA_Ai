// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import {
  clearAuthSession,
  getAuthSession,
  getAuthorizationHeader,
  storeAuthSession,
  type AuthSession,
} from "@/lib/auth/token-store";

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();

  get length(): number {
    return this.values.size;
  }

  clear(): void {
    this.values.clear();
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  key(index: number): string | null {
    return Array.from(this.values.keys())[index] ?? null;
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

const SESSION: AuthSession = {
  accessToken: "access-1",
  tokenType: "bearer",
  expiresAt: "2099-01-01T00:00:00Z",
  userId: "u1",
  username: "alice",
  companyId: "c1",
};

describe("auth token store", () => {
  beforeEach(() => {
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: new MemoryStorage(),
    });
  });

  it("保存并生成 Authorization header", () => {
    storeAuthSession(SESSION);

    expect(getAuthSession()).toEqual(SESSION);
    expect(getAuthorizationHeader()).toBe("bearer access-1");
  });

  it("过期 token 会被自动清理", () => {
    storeAuthSession({ ...SESSION, expiresAt: "2000-01-01T00:00:00Z" });

    expect(getAuthSession()).toBeNull();
    expect(window.localStorage).toHaveLength(0);
  });

  it("显式清理 session", () => {
    storeAuthSession(SESSION);
    clearAuthSession();

    expect(getAuthorizationHeader()).toBeNull();
  });

  it("受限浏览器拒绝读取 storage 时安全降级", () => {
    const restrictedStorage: Storage = {
      length: 0,
      clear() {
        throw new DOMException("blocked", "SecurityError");
      },
      getItem() {
        throw new DOMException("blocked", "SecurityError");
      },
      key() {
        return null;
      },
      removeItem() {
        throw new DOMException("blocked", "SecurityError");
      },
      setItem() {
        throw new DOMException("blocked", "SecurityError");
      },
    };
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: restrictedStorage,
    });

    expect(() => getAuthSession()).not.toThrow();
    expect(getAuthSession()).toBeNull();
    expect(() => storeAuthSession(SESSION)).not.toThrow();
    expect(() => clearAuthSession()).not.toThrow();
  });
});
