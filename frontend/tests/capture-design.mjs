import { chromium } from "@playwright/test";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
const token = (
  await readFile(process.env.TRADECASE_E2E_TOKEN_FILE, "utf8")
).trim();
const base = process.env.TRADECASE_WEB_URL || "http://127.0.0.1:3300";
const output = path.resolve("design/rounds/01");
await mkdir(output, { recursive: true });
const browser = await chromium.launch();
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  await page.addInitScript(
    (value) => sessionStorage.setItem("tradecase-token", value),
    token,
  );
  await page.goto(base);
  await page
    .getByRole("heading", { name: "从一封询盘，走向下一次机会。" })
    .waitFor();
  await page.locator(".loading").waitFor({ state: "hidden" });
  await page.screenshot({
    path: path.join(output, "dashboard-desktop.png"),
    fullPage: true,
  });
  const frozen = await page.evaluate(() => {
    const html = document.documentElement.cloneNode(true);
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
    html.querySelector("head").appendChild(style);
    return "<!DOCTYPE html>\n" + html.outerHTML;
  });
  await writeFile(path.join(output, "dashboard-render.html"), frozen);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: path.join(output, "dashboard-mobile.png"),
    fullPage: true,
  });
} finally {
  await browser.close();
}
