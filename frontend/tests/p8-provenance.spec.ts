import { test, expect } from "@playwright/test";
import { readFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";

test.skip(
  !process.env.TRADECASE_E2E_TOKEN_FILE,
  "Requires isolated actual API and DB",
);

test("P9-T004 provenance and conflicts remain reviewable on desktop and mobile", async ({
  page,
}) => {
  const token = (
    await readFile(process.env.TRADECASE_E2E_TOKEN_FILE!, "utf8")
  ).trim();
  const headers = { Authorization: `Bearer ${token}` };
  await page.addInitScript(
    (value) => sessionStorage.setItem("tradecase-token", value),
    token,
  );
  const raw = "SYNTHETIC ONLY. Company name: Example; address unresolved.";
  const created = await page.request.post("/api/pilot/cases", {
    headers,
    data: {
      title: "P8 synthetic conflicting buyer",
      raw_content: raw,
      classification: "synthetic",
      synthetic: true,
      dataset_id: `browser-${Date.now()}`,
      dataset_sha256: createHash("sha256").update(raw).digest("hex"),
      rights_reference: "SYNTHETIC_TEST_ONLY",
      source_locator: "fixture.txt:line:1",
      captured_at: new Date(Date.now() - 60000).toISOString(),
      retention_until: new Date(Date.now() + 86400000).toISOString(),
    },
  });
  expect(created.status()).toBe(201);
  const c = await created.json();
  const added = await page.request.post(`/api/cases/${c.id}/sources`, {
    headers: { ...headers, "Idempotency-Key": "browser-source" },
    data: {
      case_version: c.version,
      url: "https://synthetic.example.org/notice",
      title: "Synthetic conflicting address",
      captured_at: new Date(Date.now() - 60000).toISOString(),
      text: "SYNTHETIC ONLY. Example address is B, not A.",
      excerpt: "Example address is B, not A.",
      claim: "Example address is A.",
      locator: "notice.txt:line:1",
      relation: "contradicts",
      expires_at: new Date(Date.now() - 30000).toISOString(),
    },
  });
  expect(added.ok()).toBeTruthy();
  const evidenceResponse = await page.request.get(
    `/api/cases/${c.id}/evidence`,
    { headers },
  );
  const evidence = await evidenceResponse.json();
  expect(evidence.links[0].relation).toBe("contradicts");
  expect(evidence.conflicts).toHaveLength(1);
  const dir = process.env.TRADECASE_SCREENSHOT_DIR || "test-results/p8-render";
  await mkdir(dir, { recursive: true });
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  for (const [round, width, height] of [
    ["desktop", 1440, 1000],
    ["mobile", 390, 844],
  ] as const) {
    await page.setViewportSize({ width, height });
    await page.goto(`/cases/${c.id}`);
    await expect(page.locator(".case-status")).toContainText("版本 2");
    await expect(page.locator(".claim").first()).toContainText(
      "Example address is A.",
    );
    await expect(
      page.getByText("客户待确认 · 地区待确认", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("有 1 处来源互相矛盾，需要人工判断。", { exact: true }),
    ).toBeVisible();
    await page.locator(".claim .source-links button").first().click();
    const modal = page.getByRole("dialog");
    await expect(modal).toContainText("notice.txt:line:1");
    await expect(modal).toContainText("来源与主张冲突");
    await expect(modal).toContainText("已过期，需要重新核查");
    await expect(modal.locator("blockquote")).toHaveText(
      "Example address is B, not A.",
    );
    await expect(modal.locator(".snapshot")).toContainText("SYNTHETIC ONLY.");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBeTruthy();
    const unlabeled = await page
      .locator("button:visible")
      .evaluateAll(
        (buttons) =>
          buttons.filter(
            (b) =>
              !b.textContent?.trim() &&
              !b.getAttribute("aria-label") &&
              !b.getAttribute("title"),
          ).length,
      );
    expect(unlabeled).toBe(0);
    await page.screenshot({
      path: path.join(dir, `provenance-${round}.png`),
      fullPage: true,
    });
    await page.keyboard.press("Escape");
    await expect(modal).not.toBeVisible();
  }
  const frozen = await page.request.get(`/api/cases/${c.id}/pilot-export`, {
    headers,
  });
  // A manual snapshot has unknown origin even when its parent Case is synthetic.
  // The real data export needs a separately pinned current subject grant.
  expect(frozen.status()).toBe(403);
  const scope = await page.request.get(
    `/api/cases/${c.id}/pilot-export-scope`,
    { headers },
  );
  expect((await scope.json()).requires_data_grant).toBe(true);
  expect(errors).toEqual([]);
});
