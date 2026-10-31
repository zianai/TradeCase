import { test, expect } from "@playwright/test";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

test.skip(
  !process.env.TRADECASE_LIVE_CASE_ID,
  "Explicit authorized synthetic followup only",
);
test("actual SDK receipt remains synthetic and pending in the real review UI", async ({
  page,
}) => {
  const token = (
    await readFile(process.env.TRADECASE_E2E_TOKEN_FILE!, "utf8")
  ).trim();
  const caseId = process.env.TRADECASE_LIVE_CASE_ID!;
  const directory = process.env.TRADECASE_SCREENSHOT_DIR!;
  await mkdir(directory, { recursive: true });
  await page.addInitScript(
    (value) => sessionStorage.setItem("tradecase-token", value),
    token,
  );
  const headers = { Authorization: `Bearer ${token}` };
  const response = await page.request.get(`/api/cases/${caseId}`, { headers });
  expect(response.ok()).toBeTruthy();
  const c = await response.json();
  expect(c.synthetic).toBe(true);
  expect(c.status).toBe("NEEDS_REVIEW");
  expect(c.outbound_enabled).toBe(false);
  const pending = await page.request.get("/api/approvals", { headers });
  expect(
    (await pending.json()).every(
      (item: { status: string }) => item.status === "PENDING",
    ),
  ).toBe(true);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  for (const [label, width, height] of [
    ["desktop", 1440, 1000],
    ["mobile", 390, 844],
  ] as const) {
    await page.setViewportSize({ width, height });
    await page.goto(`/cases/${caseId}`);
    await expect(
      page.getByRole("heading", { name: /Synthetic live SDK followup/ }),
    ).toBeVisible();
    await expect(
      page.locator(".source-catalog .source-record").first(),
    ).toBeVisible();
    expect(await page.locator(".claim").count()).toBeGreaterThan(0);
    await page.screenshot({
      path: path.join(directory, `live-evidence-${label}.png`),
      fullPage: true,
    });
    await page
      .locator(".source-catalog .source-record")
      .filter({ hasText: "Fictional ambiguity fixture" })
      .click();
    await expect(page.locator(".snapshot")).toContainText(
      "SYNTHETIC E2 SOURCE ONLY",
    );
    await page.screenshot({
      path: path.join(directory, `live-source-${label}.png`),
      fullPage: true,
    });
    await page.keyboard.press("Escape");
    await page.getByRole("tab", { name: /邮件草稿与审核/ }).click();
    await expect(page.locator(".mail-draft")).toBeVisible();
    await page.screenshot({
      path: path.join(directory, `live-pending-review-${label}.png`),
      fullPage: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  }
  const actions = await page.request.get(
    `/api/cases/${caseId}/outbound-actions`,
    { headers },
  );
  expect(await actions.json()).toEqual([]);
  expect(errors).toEqual([]);
  await writeFile(
    path.join(directory, "browser-acceptance.json"),
    JSON.stringify(
      {
        mode: "E2 synthetic SDK result displayed through actual API/browser",
        case_id: caseId,
        source_visible: true,
        desktop_mobile: true,
        human_review: "pending",
        approved: false,
        browser_api_writes: 0,
        external_sends: 0,
        page_errors: errors,
        limitation:
          "Email draft is deterministic kernel output; only one research response used a live model",
      },
      null,
      2,
    ),
  );
});
