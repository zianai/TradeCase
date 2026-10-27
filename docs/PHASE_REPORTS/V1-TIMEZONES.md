# V1采购截止时间：命名时区与仅有日期

基线 `6ae0e6a`，原分支增量实现；没有发送邮件、外部写入或V2开发。

## 规则与证据

- 支持已实现的数字GMT/UTC偏移，以及IANA时区（如`America/New_York`、`Europe/London`、`Asia/Jerusalem`）；明确名称映射包括Jerusalem、London、US Eastern/Central/Pacific、Beijing、Tokyo和Singapore Time。模糊缩写如CST、没有时区的具体时刻、未知时区保持`needs_review`，不从国家或系统时区猜测。
- 使用Python `zoneinfo`按公告日期转换，夏令时回拨中的重复时间和跳时中不存在的时间均`needs_review`。数据库或指定时区不可用时也待复核。此次环境的系统tzdb为`2026b-rearguard`，记录于`timezone-database.json`；不同环境可能更新时区规则。
- 仅有日期时不生成精确`deadline_utc`，不将未来日期视为open。有明确时区时，以**次日当地零点**作为最晚可能界限，到达界限后才能确认expired；之前保持needs_review。没有时区时使用更宽的保守上界：该日期后的第二日UTC零点（覆盖合法UTC偏移绝对值小于24小时），不推测公告所在地。界限是保守判断上界，不是实际截止时间。无法计算边界时待复核。
- 识别更多常见截止声明标签；识别到多个声明、不同时间或单条声明无法解析时保持待复核。支持的语法和名称是有限集合，不能保证发现所有其他自然语言表述或隐含补遗。
- Case仍要求支持性官方来源Evidence、来源URL、完整逐字截止声明与已索引快照一致。仅引用日期或声明前缀不能作为完整证据。命名时区的解析UTC或日期上界也纳入草稿审核绑定；时区数据库变更导致换算结果变化时，旧审核失效。来源真实性和更新仍需人工确认。

## 实际验证

- 初始红灯记录 `docs/evidence/V1-timezones/red.log`；定向`pytest` **31项通过**，覆盖夏令时重叠/缺口、冬夏偏移、UTC和无时区日期上界、截止边界、闰日、负零/45分钟偏移、不支持时区、数据库缺失、冲突、截断引用、快照篡改和时区换算变化导致审核失效。
- 五条已有UNGM真实历史公告从同一来源摘录重新生成：5/5严格验证通过，五次completed尝试均被拒绝；四条expired、一条冲突needs_review。与前次相同的UTC结论和Evidence/快照绑定hash逐项比较一致。见 `real-case-gates.json`；原先5个数字偏移Case也分别通过strict校验。
- `make check` exit0：compileall、Ruff、**347项pytest通过**、许可证和源码映射检查通过，见`final-regression.log`。P6原有8个Case另行strict验证均通过。双宿主项目Skill已同步，第二次同步为unchanged。

## 可复现

```bash
uv run python tools/run_p7_public_procurements.py --out-root cases/timezone-repeat --evidence-out cases/timezone-repeat-evidence
uv run tradecase validate --case cases/timezone-repeat/unicef-318181 --strict
PATH="$PWD/.venv/bin:$PATH" make check
```

输出目录使用新名字；案例使用已保存的来源摘录，不重新抓取或核实公告后续补遗。真实业务操作仍需要人工确认当前公告、资格、附件和实际截止时刻；即便状态open也没有发送或投标授权。
