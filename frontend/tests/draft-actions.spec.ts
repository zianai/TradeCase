import { test, expect, Page } from "@playwright/test";

const facts =
  "Our recorded price is USD 12.50. Delivery date remains unconfirmed.\nNo certification claim has been verified.";
const original = `Dear Purchasing Team,\n\n${facts}\n\nBest regards,\nSales Team`;

async function draftWorkspace(
  page: Page,
  options: { role?: string; queued?: boolean } = {},
) {
  const writes: {
    path: string;
    body: Record<string, unknown>;
    key?: string;
  }[] = [];
  let cancelled = false;
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (request.method() !== "GET") {
      writes.push({
        path: pathname,
        body: request.postDataJSON(),
        key: request.headers()["idempotency-key"],
      });
      if (pathname === "/api/outbound-actions/queued/cancel") cancelled = true;
      return route.fulfill({
        json: { status: cancelled ? "CANCELLED" : "SUCCEEDED" },
      });
    }
    if (pathname === "/api/me")
      return route.fulfill({ json: { role: options.role ?? "reviewer" } });
    if (pathname === "/api/settings")
      return route.fulfill({
        json: { runtime: "fake", outbound_enabled: false },
      });
    if (pathname === "/api/cases/tone")
      return route.fulfill({
        json: {
          id: "tone",
          title: "Synthetic courtesy edit",
          status: "NEEDS_REVIEW",
          version: 7,
          outbound_enabled: false,
        },
      });
    if (pathname.endsWith("/artifacts"))
      return route.fulfill({
        json: [
          {
            id: "draft-1",
            kind: "draft",
            version: 1,
            hash: "a".repeat(64),
            content: JSON.stringify({
              subject: "Product inquiry",
              recipient_email: "test@example.invalid",
              body_text: original,
            }),
          },
        ],
      });
    if (pathname.endsWith("/outbound-actions"))
      return route.fulfill({
        json: options.queued
          ? [
              {
                id: "queued",
                status: cancelled ? "CANCELLED" : "PENDING",
                case_version: 7,
              },
              { id: "running", status: "RUNNING", case_version: 7 },
              {
                id: "uncertain",
                status: "DELIVERY_UNCERTAIN",
                case_version: 7,
              },
            ]
          : [],
      });
    if (pathname.endsWith("/events") && !new URL(request.url()).search)
      return route.fulfill({
        contentType: "text/event-stream",
        body: ": heartbeat\n\n",
      });
    return route.fulfill({ json: [] });
  });
  await page.goto("/cases/tone?tab=draft");
  await expect(page.locator(".mail-draft")).toHaveText(original);
  return writes;
}

test("three courtesy tones preserve facts and signature, remain unsaved, and save only through the versioned editor", async ({
  page,
}) => {
  const writes = await draftWorkspace(page);
  await page.getByRole("button", { name: "编辑草稿", exact: true }).click();
  const body = page.getByLabel("英文正文", { exact: true });
  for (const [label, greeting, closing] of [
    ["专业", "Dear", "Kind regards,"],
    ["简洁", "Hello", "Regards,"],
    ["友好", "Hi", "Warm regards,"],
  ]) {
    await page
      .getByRole("button", { name: `${label}语气`, exact: true })
      .click();
    await expect(body).toHaveValue(
      `${greeting} Purchasing Team,\n\n${facts}\n\n${closing}\nSales Team`,
    );
    await expect(page.locator(".tone-assistance")).toContainText("尚未保存");
    await expect(page.getByLabel("邮件主题", { exact: true })).toHaveValue(
      "Product inquiry",
    );
    expect(writes).toHaveLength(0);
  }
  await page.getByRole("button", { name: "取消修改", exact: true }).click();
  await expect(page.locator(".mail-draft")).toHaveText(original);
  await page.getByRole("button", { name: "编辑草稿", exact: true }).click();
  await expect(body).toHaveValue(original);
  await page.getByRole("button", { name: "友好语气", exact: true }).click();
  await page.getByRole("button", { name: "保存新版本", exact: true }).click();
  await expect(page.locator(".mail-draft")).toBeVisible();
  expect(writes).toHaveLength(1);
  expect(writes[0].path).toBe("/api/cases/tone/draft");
  expect(writes[0].body).toEqual({
    case_version: 7,
    subject: "Product inquiry",
    body: `Hi Purchasing Team,\n\n${facts}\n\nWarm regards,\nSales Team`,
  });
});

test("reviewer cancels only a pending external action with a reason and current case version", async ({
  page,
}) => {
  const writes = await draftWorkspace(page, { queued: true });
  await page.locator(".outbound-panel > summary").click();
  const cancel = page.getByRole("button", {
    name: "取消待执行动作",
    exact: true,
  });
  await expect(cancel).toHaveCount(1);
  await expect(cancel).toBeDisabled();
  await page
    .getByLabel("取消待执行动作的原因", { exact: true })
    .fill("Synthetic test: reviewer withdrew the queued action.");
  await cancel.click();
  await expect(cancel).toHaveCount(0);
  await expect(page.locator(".receipt").first()).toContainText("已取消");
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({
    path: "/api/outbound-actions/queued/cancel",
    body: {
      case_version: 7,
      reason: "Synthetic test: reviewer withdrew the queued action.",
    },
  });
  expect(writes[0].key).toBeTruthy();
});

test("viewer cannot see the queued action cancellation control", async ({
  page,
}) => {
  const writes = await draftWorkspace(page, { queued: true, role: "viewer" });
  await page.locator(".outbound-panel > summary").click();
  await expect(page.locator(".receipt")).toHaveCount(3);
  await expect(
    page.getByRole("button", { name: "取消待执行动作", exact: true }),
  ).toHaveCount(0);
  expect(writes).toHaveLength(0);
});
