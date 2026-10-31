import { test, expect } from "@playwright/test";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const enabled = Boolean(process.env.TRADECASE_E2E_TOKEN_FILE);
test.skip(
  !enabled,
  "Set TRADECASE_E2E_TOKEN_FILE for a real local API + DB browser acceptance run.",
);

test("real API import → research → source → review → draft revision → follow-up", async ({
  page,
}) => {
  const token = (
    await readFile(process.env.TRADECASE_E2E_TOKEN_FILE!, "utf8")
  ).trim();
  await page.addInitScript(
    (value) => sessionStorage.setItem("tradecase-token", value),
    token,
  );
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const directory = path.resolve("design/rounds/01");
  await mkdir(directory, { recursive: true });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "从一封询盘，走向下一次机会。" }),
  ).toBeVisible();
  await expect(
    page.getByText("当前为离线模拟环境", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "导入询盘", exact: true }).click();
  await page.getByRole("button", { name: "合成演示", exact: true }).click();
  const title = "Browser acceptance · synthetic " + Date.now();
  await page.getByLabel("案件标题").fill(title);
  await page.getByLabel("演示场景").selectOption("case_strong");
  await page.getByRole("button", { name: "创建案件", exact: true }).click();
  await expect(page).toHaveURL(/\/cases\/[a-zA-Z0-9_-]+$/);
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  const caseId = new URL(page.url()).pathname.split("/").at(-1)!;
  await page.locator(".case-metadata summary").click();
  await page.getByLabel("优先级（0–100）").fill("90");
  await page
    .getByLabel("标签", { exact: true })
    .fill("browser-acceptance, synthetic");
  await page.getByRole("button", { name: "保存案件信息", exact: true }).click();
  await expect(page.locator(".case-status")).toContainText("版本 2");
  await page.locator(".case-metadata summary").click();
  await page.getByRole("button", { name: "开始调查", exact: true }).click();
  await expect(page.getByRole("button", { name: /查看待审核项/ })).toBeVisible({
    timeout: 60000,
  });
  await expect(
    page.locator(".source-catalog .source-record").first(),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(directory, "case-desktop.png"),
    fullPage: true,
  });
  await page.locator(".source-catalog .source-record").first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.locator(".snapshot")).not.toContainText("正在读取…");
  await expect(page.locator(".snapshot")).not.toBeEmpty();
  await page.screenshot({
    path: path.join(directory, "source-snapshot.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "关闭来源" }).click();
  await page.getByRole("tab", { name: "风险与规则" }).click();
  await expect(page.locator(".risk-row")).toHaveCount(2);
  await page.getByRole("tab", { name: /邮件草稿与审核/ }).click();
  await expect(page.locator(".mail-draft")).toContainText("Thank you");
  await page
    .getByLabel("审核说明")
    .fill(
      "Synthetic browser acceptance: checked evidence and conservative draft. No send authorized.",
    );
  await page.getByRole("button", { name: "审核并批准", exact: true }).click();
  await expect(page.locator(".case-status")).toContainText("可跟进", {
    timeout: 60000,
  });
  await page.getByRole("button", { name: "编辑草稿", exact: true }).click();
  await page.getByRole("button", { name: "友好语气", exact: true }).click();
  await expect(page.locator(".tone-assistance")).toContainText("尚未保存");
  await expect(page.getByLabel("英文正文")).toHaveValue(/Warm regards,/);
  const original = await page.getByLabel("英文正文").inputValue();
  await page
    .getByLabel("英文正文")
    .fill(original + "\n\nPlease confirm your destination port.");
  await page.getByRole("button", { name: "保存新版本", exact: true }).click();
  // Superseded reviews stay on record, folded under the current decision.
  await page.locator(".approval-history > summary").first().click();
  await expect(
    page.locator(".approval-card").filter({ hasText: "版本失效" }),
  ).toBeVisible();
  const pending = page.locator(".approval-card").filter({
    has: page.getByRole("button", { name: "审核并批准", exact: true }),
  });
  await expect(pending).toBeVisible();
  await pending
    .getByLabel("审核说明")
    .fill(
      "Synthetic second approval bound to revised hash; no send authorized.",
    );
  await pending
    .getByRole("button", { name: "审核并批准", exact: true })
    .click();
  await expect(page.locator(".case-status")).toContainText("可跟进", {
    timeout: 60000,
  });
  await page.getByText("版本差异（前一版 → 当前版）", { exact: true }).click();
  await expect(
    page
      .locator(".diff .added")
      .filter({ hasText: "Please confirm your destination port." }),
  ).toHaveCount(1);
  await expect(page.locator(".diff")).toContainText("Warm regards,");
  await page.screenshot({
    path: path.join(directory, "draft-approval-desktop.png"),
    fullPage: true,
  });
  await page.getByRole("tab", { name: "跟进时间线" }).click();
  await expect(page.locator(".followup-row").first()).toBeVisible();
  await page
    .getByLabel("下一步行动")
    .fill("Synthetic follow-up: confirm destination port");
  await page.getByRole("button", { name: "创建跟进", exact: true }).click();
  const followup = page
    .locator(".followup-row")
    .filter({ hasText: "Synthetic follow-up: confirm destination port" });
  await expect(followup).toBeVisible();
  await followup.getByRole("button", { name: "标记完成" }).click();
  await expect(followup).toContainText("已完成");
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出 JSON ↗", exact: true }).click();
  const result = await downloadPromise;
  expect(result.suggestedFilename()).toBe(`tradecase-${caseId}.json`);
  await page.reload();
  await expect(page.locator(".case-status")).toContainText("可跟进");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("tab", { name: /邮件草稿与审核/ }).click();
  await expect(page.locator(".mail-draft")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: path.join(directory, "case-mobile.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(
    page.getByRole("link", { name: title, exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(directory, "dashboard-desktop.png"),
    fullPage: true,
  });
  const frozen = await page.evaluate(() => {
    const html = document.documentElement.cloneNode(true) as HTMLElement;
    html
      .querySelectorAll("script,nextjs-portal,link")
      .forEach((el) => el.remove());
    const style = document.createElement("style");
    style.textContent = Array.from(document.styleSheets)
      .flatMap((sheet) => {
        try {
          return Array.from(sheet.cssRules).map((rule) => rule.cssText);
        } catch {
          return [];
        }
      })
      .join("\n");
    html.querySelector("head")?.appendChild(style);
    return "<!DOCTYPE html>\n" + html.outerHTML;
  });
  await writeFile(path.join(directory, "dashboard-render.html"), frozen);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: path.join(directory, "dashboard-mobile.png"),
    fullPage: true,
  });
  const actionResponse = await page.request.get(
    `/api/cases/${caseId}/outbound-actions`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  expect(actionResponse.ok()).toBeTruthy();
  expect(await actionResponse.json()).toEqual([]);
  expect(errors).toEqual([]);
  await writeFile(
    path.join(directory, "browser-e2e.json"),
    JSON.stringify(
      {
        case_id: caseId,
        title,
        verified: [
          "real Postgres API through Next proxy",
          "explicit synthetic import",
          "versioned priority and tag editing",
          "research workflow",
          "source snapshot",
          "two risk checks",
          "version-bound review",
          "unsaved courtesy tone preview then versioned save",
          "draft edit invalidated prior approval",
          "reapproval",
          "followup create and complete",
          "JSON export",
          "refresh recovery",
          "390px no overflow",
        ],
        page_errors: errors,
        external_sends: 0,
        mode: "synthetic_offline",
      },
      null,
      2,
    ),
  );
});

test("real API knowledge versions remain separate and explicitly unverified", async ({
  page,
}) => {
  const token = (
    await readFile(process.env.TRADECASE_E2E_TOKEN_FILE!, "utf8")
  ).trim();
  await page.addInitScript(
    (value) => sessionStorage.setItem("tradecase-token", value),
    token,
  );
  await page.goto("/sources");
  await page.getByRole("button", { name: "登记资料", exact: true }).click();
  const title = "Synthetic browser knowledge " + Date.now();
  await page.getByLabel("资料标题", { exact: true }).fill(title);
  await page
    .getByLabel("资料内容", { exact: true })
    .fill(
      "SYNTHETIC OFFLINE DATA. Packaging dimensions require manual confirmation. No certification is stated.",
    );
  await page.getByRole("button", { name: "保存资料版本", exact: true }).click();
  await expect(page.locator(".knowledge-reader h3")).toHaveText(
    title + " · 版本 1",
  );
  await expect(page.locator(".knowledge-reader")).toContainText(
    "用户提供 · 尚未核实",
  );
  await page.getByRole("button", { name: "修订当前版本", exact: true }).click();
  const first = await page.getByLabel("资料内容", { exact: true }).inputValue();
  await page
    .getByLabel("资料内容", { exact: true })
    .fill(first + "\nVersion two: confirm preferred carton dimensions.");
  await page.getByRole("button", { name: "保存资料版本", exact: true }).click();
  await expect(page.locator(".knowledge-reader h3")).toHaveText(
    title + " · 版本 2",
  );
  await page.getByLabel("知识版本 " + title).selectOption("1");
  await expect(page.locator(".knowledge-reader h3")).toHaveText(
    title + " · 版本 1",
  );
  await expect(page.locator(".knowledge-reader .snapshot")).not.toContainText(
    "Version two",
  );
  await page.screenshot({
    path: "design/rounds/01/knowledge-versions.png",
    fullPage: true,
  });
});
