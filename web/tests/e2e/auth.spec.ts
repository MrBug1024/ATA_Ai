// tests/e2e/auth.spec.ts
import { test, expect } from "@playwright/test";

const TEST_LOGIN_IDENTIFIER = process.env.E2E_LOGIN_IDENTIFIER;
const TEST_PASSWORD = process.env.E2E_PASSWORD;

test.describe("认证流程", () => {
  test("开放模式或后端账号均可进入应用", async ({ page }) => {
    await page.goto("/login");
    await page.waitForFunction(
      () => location.pathname === "/chat" || document.querySelector("#login-identifier"),
      undefined,
      { timeout: 10_000 }
    );

    if (new URL(page.url()).pathname === "/chat") {
      await expect(page).toHaveURL(/\/chat/);
      return;
    }

    if (!TEST_LOGIN_IDENTIFIER || !TEST_PASSWORD) {
      test.skip(true, "认证启用时需配置 E2E_LOGIN_IDENTIFIER 和 E2E_PASSWORD");
      return;
    }
    await page.getByPlaceholder("请输入用户名").fill(TEST_LOGIN_IDENTIFIER);
    await page.getByPlaceholder(/密码/i).fill(TEST_PASSWORD);
    await page.getByRole("button", { name: /登录/i }).click();
    await expect(page).toHaveURL(/\/chat/, { timeout: 10_000 });
  });
});
