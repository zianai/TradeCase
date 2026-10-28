import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";

test.skip(
  !process.env.TRADECASE_E2E_TOKEN_FILE,
  "Requires the actual local API with an authorized synthetic-test reviewer token.",
);

test("manual snapshot and reviewer input preserve unknown status and require explicit source confirmations", async ({
  page,
}) => {
  const token = (
    await readFile(process.env.TRADECASE_E2E_TOKEN_FILE!, "utf8")
  ).trim();
  await page.addInitScript(
    (value) => sessionStorage.setItem("tradecase-token", value),
    token,
  );
  await page.goto("/");
  await page.getByRole("button", { name: "导入询盘", exact: true }).click();
  await page
    .getByLabel("案件标题", { exact: true })
    .fill("Synthetic reviewer intake " + Date.now());
  await page
    .getByLabel("询盘原文", { exact: true })
    .fill(
      "SYNTHETIC TEST DATA. Please confirm general product dimensions. No email send is authorized.",
    );
  await page.getByRole("button", { name: "创建案件", exact: true }).click();
  await expect(page).toHaveURL(/\/cases\/[a-f0-9]+$/);
  const caseId = new URL(page.url()).pathname.split("/").at(-1)!;
  await page.locator(".manual-source summary").click();
  await page
    .getByLabel("来源网页地址", { exact: true })
    .fill("https://example.com/synthetic-provenance-test");
  await page
    .getByLabel("来源标题", { exact: true })
    .fill("Synthetic authored sample; not a fetched website");
  const excerpt = "SYNTHETIC excerpt: dimensions require confirmation.";
  await page
    .getByLabel("完整快照内容", { exact: true })
    .fill("Authored only for UI testing. " + excerpt);
  await page.getByLabel("逐字引用片段", { exact: true }).fill(excerpt);
  await page
    .getByLabel("需要核实的主张", { exact: true })
    .fill("The supplied test excerpt asks to confirm dimensions.");
  await page.getByRole("button", { name: "保存人工来源", exact: true }).click();
  await expect(page.locator(".manual-source .notice.good")).toContainText(
    "主张仍为待核实",
  );
  await expect(page.locator(".case-status")).toContainText("版本 2");
  await page.locator(".source-catalog .source-record").first().click();
  await expect(page.getByRole("dialog")).toContainText("系统未执行在线抓取");
  await expect(page.locator(".snapshot")).toContainText(excerpt);
  await page.getByRole("button", { name: "关闭来源", exact: true }).click();
  await page.locator(".advanced-review summary").click();
  const editor = page.getByLabel("高级复核输入（JSON）", { exact: true });
  await expect(editor).toBeVisible();
  const payload = JSON.parse(await editor.inputValue());
  expect(payload.evidence_bindings.length).toBeGreaterThan(0);
  expect(
    payload.evidence_bindings.every(
      (binding: Record<string, unknown>) =>
        binding.source_permission_confirmed === false &&
        binding.source_role_confirmed === false,
    ),
  ).toBe(true);
  // This test explicitly acts as the reviewer of its own authored synthetic sample.
  // It does not assert that the cited site was fetched or that the claim is true.
  payload.evidence_bindings = payload.evidence_bindings.map(
    (binding: Record<string, unknown>) => ({
      ...binding,
      source_permission_confirmed: true,
      source_role_confirmed: true,
      assertion_status: "unverified",
      source_type: "other",
    }),
  );
  await editor.fill(JSON.stringify(payload, null, 2));
  await page
    .getByLabel("人工复核说明", { exact: true })
    .fill(
      "Synthetic UI acceptance only: reviewer authored the supplied test text. Source role remains other, assertion unverified, no online retrieval or official authority is claimed.",
    );
  await expect(
    page.getByRole("checkbox", {
      name: "我已确认标为现行的官方规则的来源、适用范围与有效日期。",
      exact: true,
    }),
  ).not.toBeChecked();
  await page
    .getByRole("checkbox", {
      name: "我已逐条核对引用与权限，并对本次人工判断负责。未确认的事项保持未知。",
      exact: true,
    })
    .check();
  await page
    .getByRole("button", { name: "保存人工复核版本", exact: true })
    .click();
  await expect(page.locator(".advanced-review .notice.good")).toContainText(
    "人工复核版本已保存",
  );
  const evidence = await page.request.get(`/api/cases/${caseId}/evidence`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(evidence.ok()).toBeTruthy();
  expect(
    (await evidence.json()).claims.every(
      (claim: Record<string, unknown>) => claim.classification === "UNKNOWN",
    ),
  ).toBe(true);
  const outbox = await page.request.get(
    `/api/cases/${caseId}/outbound-actions`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  expect(await outbox.json()).toEqual([]);
  await page.screenshot({
    path: "design/rounds/01/manual-source-review.png",
    fullPage: true,
  });
});
