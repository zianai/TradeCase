import { test, expect, Page } from "@playwright/test";

const hash = "b".repeat(64);
const caseId = "9745c8d1821f46eaa7f003d70da2356f";
const fixtureCase = {
  id: caseId,
  title: "木制玩具询价",
  status: "NEEDS_REVIEW",
  version: 2,
  priority: 100,
  inquiry: {
    buyer_company_hint: "Harbor Toys",
    target_country: "US",
    product_summary: "Wooden toys",
    buyer_message: "Please quote 500 units.",
  },
  assessment: {
    decision: "high_priority",
    score: 100,
    evidence_coverage: 1,
    missing_information: ["contactability"],
    reason_codes: ["ENTITY_AMBIGUOUS"],
    rule_version: "priority-v1",
    signals: {
      verified_identity: {
        value: "supported",
        rationale: "registry match",
        evidence_ids: ["ev-identity"],
      },
    },
  },
};
const unassessed = {
  id: "unassessed",
  title: "新询盘",
  status: "NEW",
  version: 1,
  priority: 0,
  inquiry: {},
};
const approval = (over = {}) => ({
  id: "current",
  case_id: caseId,
  status: "PENDING",
  action_scope: "draft_review",
  scope: "draft_review",
  artifact_hash: hash,
  case_version: 2,
  expires_at: "2026-11-06T16:21:59Z",
  ...over,
});

async function mock(page: Page) {
  await page.route("**/api/**", async (route) => {
    const { pathname } = new URL(route.request().url());
    const json = (value: unknown) => route.fulfill({ json: value });
    if (pathname === "/api/settings")
      return json({ runtime: "fake", outbound_enabled: false });
    if (pathname === "/api/me") return json({ role: "reviewer" });
    if (pathname === "/api/cases") return json([fixtureCase, unassessed]);
    if (pathname === `/api/cases/${caseId}`) return json(fixtureCase);
    if (pathname === "/api/approvals")
      return json([
        approval(),
        approval({ id: "old", status: "INVALIDATED", case_version: 1 }),
      ]);
    if (pathname.endsWith("/evidence"))
      return json({
        claims: [
          {
            id: "c1",
            text: "Registry lists Harbor Toys as a distributor.",
            kind: "FACT",
            status: "SUPPORTED",
            subject: "inquiry",
            source_ids: ["s1"],
            data: { legacy_evidence_id: "ev-identity" },
          },
        ],
        sources: [
          {
            id: "s1",
            url: "",
            title: "",
            source_type: "government",
            license_status: "permitted",
            snapshot_hash: hash,
            captured_at: "2026-10-27T12:00:00Z",
          },
        ],
        links: [],
      });
    if (pathname.endsWith("/artifacts"))
      return json([
        {
          id: "d2",
          kind: "reply_draft",
          version: 2,
          hash,
          content: "Dear team,\nThanks.",
        },
      ]);
    if (pathname.endsWith("/events") && !new URL(route.request().url()).search)
      return route.fulfill({
        contentType: "text/event-stream",
        body: ": heartbeat\n\n",
      });
    return json([]);
  });
}

test("dashboard names the customer and task instead of an internal case ID", async ({
  page,
}) => {
  await mock(page);
  await page.goto("/");
  const card = page.locator(".decision-preview").first();
  await expect(card).toContainText("Harbor Toys · 木制玩具询价");
  await expect(card).toContainText("回复草稿待审核");
  await expect(card).not.toContainText(caseId.slice(0, 12));
  await expect(card).not.toContainText("Case ");
});

test("priority explains itself and never presents an unassessed 0 as a score", async ({
  page,
}) => {
  await mock(page);
  await page.goto("/cases");
  const rows = page.locator("tbody tr");
  await expect(rows.nth(0).locator(".priority")).toContainText("优先跟进");
  await expect(rows.nth(0).locator(".priority")).toContainText(
    "评分 100 / 100",
  );
  await expect(rows.nth(1).locator(".priority")).toHaveText("待评估");
});

test("assessment reads as a conclusion; raw record and hash stay available but folded", async ({
  page,
}) => {
  await mock(page);
  await page.goto(`/cases/${caseId}`);
  const brief = page.getByRole("region", { name: "询盘摘要" });
  await expect(brief).toContainText("Harbor Toys");
  await expect(brief).toContainText("优先跟进");
  await expect(brief).toContainText("还缺：联系方式可用性");
  const section = page.locator(".assessment-section");
  await expect(section).toContainText("企业身份核实");
  await expect(section).toContainText(
    "Registry lists Harbor Toys as a distributor.",
  );
  await expect(section).toContainText("存在同名或多个候选企业");
  const raw = section.locator(".tech-details pre");
  await expect(raw).toBeHidden();
  await section.locator(".tech-details summary").click();
  await expect(raw).toContainText("priority-v1");
  await expect(page.locator(".source-catalog")).toContainText("政府机构");
  await expect(page.locator(".source-catalog")).not.toContainText("government");
});

test("draft review shows the current version first and folds hash and history", async ({
  page,
}) => {
  await mock(page);
  await page.goto(`/cases/${caseId}?tab=draft`);
  await expect(page.locator(".draft-meta")).toContainText("第 2 版");
  await expect(page.locator(".draft-meta")).not.toContainText("SHA256");
  const column = page.locator(".approval-column");
  await expect(column.locator("> .approvals-list > article")).toHaveCount(1);
  await expect(column.getByText(hash).first()).toBeHidden();
  await expect(column.getByText("历史审核记录（1）")).toBeVisible();
  await column.getByRole("button", { name: "查看本案调查与证据 ↗" }).click();
  await expect(page.getByRole("tab", { name: "调查与证据" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.locator(".source-catalog")).toBeVisible();
});
