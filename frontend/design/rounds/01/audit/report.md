# UI 检查报告

- 目标：design/rounds/01/dashboard-render.html
- 时间：2026-10-28T13:32:23.449Z
- 浏览器：/Users/a/Library/Caches/ms-playwright/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing 156.0.8078.4
- 结论：**fail**（fail 4，warn 7）

| 检查 | 1440x900 · default | 390x844 · default |
|---|---|---|
| console-errors | fail 1 | fail 1 |
| failed-requests | warn 1 | warn 1 |
| horizontal-overflow | ok | ok |
| clipped-text | ok | ok |
| touch-target | ok | warn 4 |
| primary-action | ok | ok |
| focus-visible | ok | ok |
| focus-hidden-stop | ok | ok |
| a11y-axe | fail 19 | fail 8 |
| font-families | ok | ok |
| off-token-colors | warn 30 | warn 20 |
| spacing-off-grid | warn 16 | warn 28 |
| gradients | ok | ok |

## 明细（只列非 ok 项，每项最多 8 条）

### 1440x900 · default

截图：1440x900-default.png，1440x900-default-full.png

**console-errors**（fail）
- Failed to load resource: net::ERR_FILE_NOT_FOUND

**failed-requests**（warn）
- file:///_next/static/chunks/%5Bturbopack%5D_browser_dev_hmr-client_hmr-client_ts_0qva5cupmdgep._.js (net::ERR_FILE_NOT_FOUND)

**a11y-axe**（fail）
- color-contrast（serious，12 处）：Elements must meet minimum color contrast ratio thresholds — .active > span > small (#94aaa0 on #2b483c, 4.06:1, needs 4.5:1)；.page-heading > div > .eyebrow (#6e8073 on #f6f5ef, 3.84:1, needs 4.5:1)；.panel > .panel-heading > div > .eyebrow (#6e8073 on #fdfcf8, 4.09:1, needs 4.5:1)；th:nth-child(1) (#637365 on #f1f2eb, 4.46:1, needs 4.5:1)；th:nth-child(2) (#637365 on #f1f2eb, 4.46:1, needs 4.5:1)
- label-content-name-mismatch（serious，7 处）：Elements must have their visible text as part of their accessible name — .brand；.active；a[aria-label="询盘案件"]；a[aria-label="决策收件箱"]；a[aria-label="跟进计划"]

**off-token-colors**（warn） token 来源：page :root，14 个颜色 token
- rgb(148, 170, 160) ×6（color）例：nav > a.nav-item.active > span > small；nav > a.nav-item > span > small；nav > a.nav-item > span > small
- rgb(199, 212, 203) ×5（color）例：aside.sidebar > nav > a.nav-item > span；aside.sidebar > nav > a.nav-item > span；aside.sidebar > nav > a.nav-item > span
- rgb(241, 242, 235) ×5（background）例：table > thead > tr > th；table > thead > tr > th；table > thead > tr > th
- rgb(119, 147, 135) ×4（border）例：div.shell > aside.sidebar > a.brand > span.brand-mark；div.shell > aside.sidebar > a.brand > span.brand-mark；div.shell > aside.sidebar > a.brand > span.brand-mark
- rgb(209, 216, 201) ×4（border）例：div.workspace > header.topbar > div.topbar-actions > span.avatar；div.workspace > header.topbar > div.topbar-actions > span.avatar；div.workspace > header.topbar > div.topbar-actions > span.avatar
- rgb(99, 115, 101) ×4（color）例：table > thead > tr > th；table > thead > tr > th；table > thead > tr > th
- rgb(230, 216, 184) ×4（border）例：tr > td > div.table-sub > span.synthetic-tag；tr > td > div.table-sub > span.synthetic-tag；tr > td > div.table-sub > span.synthetic-tag
- rgb(238, 242, 233) ×3（color）例：div.shell > aside.sidebar > a.brand > span.brand-mark；aside.sidebar > a.brand > span.brand-mark > span；div.shell > aside.sidebar > a.brand > span

**spacing-off-grid**（warn） 栅格 4px，≤2px 视为光学微调不计
- 6px ×8 例：div.workspace > header.topbar > div.topbar-actions > button.icon-button {paddingRight}；div.workspace > header.topbar > div.topbar-actions > button.icon-button {paddingLeft}；section.panel > div.panel-heading > div > span.eyebrow {marginBottom}
- 5px ×4 例：body > div.shell > aside.sidebar > nav {rowGap}；body > div.shell > aside.sidebar > nav {columnGap}；aside.sidebar > div.sidebar-bottom > p > small {marginTop}
- 14px ×2 例：body > div.shell > aside.sidebar > div.workspace-label {paddingTop}；body > div.shell > aside.sidebar > div.workspace-label {paddingBottom}
- 10px ×2 例：main#main > div.page-heading > div > span.eyebrow {marginBottom}；main#main > div.page-heading > div > p {marginTop}

清单：字体 Avenir Next、Iowan Old Style、SFMono-Regular；字号/字重 9px/500 10px/400 10px/650 10px/500 10px/550 11px/400 12px/400 12px/500 12px/550 13px/400 13px/550 14px/400 15px/650 15px/400 16px/650 18px/650 22px/400 23px/650 32px/650 46px/400；颜色 40 种（不在 token 里 30 种）；圆角 2px 4px

### 390x844 · default

截图：390x844-default.png，390x844-default-full.png

**console-errors**（fail）
- Failed to load resource: net::ERR_FILE_NOT_FOUND

**failed-requests**（warn）
- file:///_next/static/chunks/%5Bturbopack%5D_browser_dev_hmr-client_hmr-client_ts_0qva5cupmdgep._.js (net::ERR_FILE_NOT_FOUND)

**touch-target**（warn） 窄视口下小于 44px
- div.workspace > header.topbar > div.topbar-actions > button.icon-button「刷新数据」 @296,72,32,32 size=32×32
- main#main > div.page-heading > button.button「导入询盘」 @20,342,350,43 size=350×43
- div.dashboard-grid > section.panel > div.panel-heading > a.text-link「查看全部 ↗」 @291,746,58,18 size=58×18
- tbody > tr > td > a.case-name「Browser acceptance · synthetic 179319369」 @41,813,308,21 size=308×21

**a11y-axe**（fail）
- color-contrast（serious，7 处）：Elements must meet minimum color contrast ratio thresholds — .page-heading > div > .eyebrow (#6e8073 on #f6f5ef, 3.84:1, needs 4.5:1)；.panel > .panel-heading > div > .eyebrow (#6e8073 on #fdfcf8, 4.09:1, needs 4.5:1)；.decision-column > .panel-heading > div > .eyebrow (#6e8073 on #f6f5ef, 3.84:1, needs 4.5:1)；.method-note > span (#778a76 on #f6f5ef, 3.38:1, needs 4.5:1)；footer (#6f7d6d on #f6f5ef, 3.98:1, needs 4.5:1)
- label-content-name-mismatch（serious，1 处）：Elements must have their visible text as part of their accessible name — .brand

**off-token-colors**（warn） token 来源：page :root，14 个颜色 token
- rgb(119, 147, 135) ×4（border）例：div.shell > aside.sidebar > a.brand > span.brand-mark；div.shell > aside.sidebar > a.brand > span.brand-mark；div.shell > aside.sidebar > a.brand > span.brand-mark
- rgb(209, 216, 201) ×4（border）例：div.workspace > header.topbar > div.topbar-actions > span.avatar；div.workspace > header.topbar > div.topbar-actions > span.avatar；div.workspace > header.topbar > div.topbar-actions > span.avatar
- rgb(230, 216, 184) ×4（border）例：tr > td > div.table-sub > span.synthetic-tag；tr > td > div.table-sub > span.synthetic-tag；tr > td > div.table-sub > span.synthetic-tag
- rgb(110, 128, 115) ×3（color）例：main#main > div.page-heading > div > span.eyebrow；section.panel > div.panel-heading > div > span.eyebrow；section.decision-column > div.panel-heading > div > span.eyebrow
- rgb(111, 125, 109) ×3（color）例：body > div.shell > div.workspace > footer.footer；div.shell > div.workspace > footer.footer > span；div.shell > div.workspace > footer.footer > span
- rgb(238, 242, 233) ×2（color）例：div.shell > aside.sidebar > a.brand > span.brand-mark；aside.sidebar > a.brand > span.brand-mark > span
- rgb(174, 187, 171) ×2（border）例：main#main > div.stats-band；main#main > div.stats-band
- rgb(43, 72, 60) ×1（background）例：div.shell > aside.sidebar > nav > a.nav-item.active

**spacing-off-grid**（warn） 栅格 4px，≤2px 视为光学微调不计
- 14px ×14 例：body > div.shell > aside.sidebar > a.brand {paddingRight}；body > div.shell > aside.sidebar > a.brand {paddingLeft}；div.shell > aside.sidebar > nav > a.nav-item.active {paddingRight}
- 6px ×10 例：div.workspace > header.topbar > div.topbar-actions > button.icon-button {paddingRight}；div.workspace > header.topbar > div.topbar-actions > button.icon-button {paddingLeft}；main#main > div.safety-strip {rowGap}
- 10px ×4 例：body > div.shell > aside.sidebar > a.brand {rowGap}；body > div.shell > aside.sidebar > a.brand {columnGap}；main#main > div.page-heading > div > span.eyebrow {marginBottom}

清单：字体 Avenir Next、Iowan Old Style；字号/字重 9px/650 9px/400 9px/500 10px/400 10px/550 11px/650 11px/400 12px/400 12px/500 12px/550 13px/550 14px/400 15px/650 15px/400 17px/650 20px/400 23px/650 26px/650 38px/400；颜色 29 种（不在 token 里 20 种）；圆角 4px 2px

## 未覆盖

- 只测加载后的静态状态和键盘焦点；hover、按下、拖拽和真实任务流程没有测。
- 触点的间距豁免是近似计算；SVG 图标颜色不在颜色清单里。
- 渐变或图片上的文字对比度由 axe 标为“无法判断”的部分需要人工看。
- 这些检查只能说明“有没有错”，不能说明“好不好看”。
