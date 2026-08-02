// tests/e2e/chat.spec.ts
import { test, expect } from "@playwright/test";

test.describe("对话流程", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login");
    await page.waitForFunction(
      () => location.pathname === "/chat" || document.querySelector("#login-identifier"),
      undefined,
      { timeout: 10_000 }
    );
    if (new URL(page.url()).pathname === "/chat") return;

    const loginIdentifier = process.env.E2E_LOGIN_IDENTIFIER;
    const password = process.env.E2E_PASSWORD;
    if (!loginIdentifier || !password) {
      test.skip(true, "认证启用时需配置 E2E_LOGIN_IDENTIFIER 和 E2E_PASSWORD");
      return;
    }
    await page.getByPlaceholder("请输入用户名").fill(loginIdentifier);
    await page.getByPlaceholder(/密码/i).fill(password);
    await page.getByRole("button", { name: /登录/i }).click();
    await expect(page).toHaveURL(/\/chat/, { timeout: 10_000 });
  });

  test("新建对话并发送消息", async ({ page }) => {
    await page.goto("/chat");
    const input = page.getByPlaceholder(/发送消息/);
    await input.fill("你好");
    await page.getByRole("button", { name: /发送/i }).click();
    await expect(page).toHaveURL(/\/chat\/.+/, { timeout: 10_000 });
    await expect(page.getByText("你好")).toBeVisible();

    const assistantReply = page.locator('[data-role="assistant"] .wrap-break-word').last();
    await expect(assistantReply).toContainText(/\S+/, { timeout: 60_000 });

    await page.reload();
    await expect(page.getByText("你好", { exact: true })).toBeVisible({ timeout: 15_000 });
    await expect(
      page.locator('[data-role="assistant"] .wrap-break-word').last()
    ).toContainText(/\S+/, { timeout: 15_000 });
  });

  test("侧边栏搜索过滤对话", async ({ page }) => {
    await page.goto("/chat");
    await page.getByLabel("搜索对话").click();
    await page.getByPlaceholder("搜索对话...").fill("不存在的关键词xyz");
    await expect(page.getByText("暂无对话")).toBeVisible();
  });
});
