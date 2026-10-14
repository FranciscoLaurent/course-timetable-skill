# course-timetable · 说一句话，出课表

![课表.skill —— 一句话生成，电脑端手机端视图，一键导出图片](docs/social-preview.jpg)

**把课程信息用打字或语音说给 AI，自动生成一张单文件、离线、可打印的课表网页。**

按周查看 / 学期总览一键切换 · 电脑版 / 手机版 · 可导出 PDF 和图片。

> **English:** An AI agent skill that turns spoken or typed course info into a single-file, offline
> timetable webpage — switch between per-week and whole-semester views, desktop and phone layouts,
> and export to PDF or PNG. Parsing is Chinese-first (中文课表), and the output page is fully offline.
> Requires only Python 3 (stdlib); Node and a browser are optional.

![电脑版](docs/preview-desktop.png)

<table>
<tr>
<td width="50%"><img src="docs/preview-mobile.png" alt="手机版"></td>
<td width="50%"><img src="docs/preview-overview.png" alt="学期总览"></td>
</tr>
<tr>
<td align="center">手机版（真机自动铺满屏幕）</td>
<td align="center">学期总览（同一格多门课叠放，各带周次）</td>
</tr>
</table>

---

## 它能帮你做什么

你对 AI 说一句人话，它把课表做好，交付一个网页文件给你：

> 「我周一周三 5-7 节上硕士英语，周二周四 1-2 节机器学习，周四 3-4 节历史学专题，帮我做个课表」

它会回你一张**解析结果表**让你核对，再给你一个 `课表.html`：

| # | 星期 | 节次 | 课程 | 周次 | 教室 |
|---|------|------|------|------|------|
| 1 | 周一 | 5-7 | 硕士英语 | 8-16 | — |
| 2 | 周二 | 1-2 | 机器学习 | 8-16 | — |
| 3 | 周三 | 5-7 | 硕士英语 | 8-16 | — |
| 4 | 周四 | 1-2 | 机器学习 | 8-16 | — |
| 5 | 周四 | 3-4 | 历史学专题 | 8-16 | — |

之后你就能：

- **按周看**：下拉选「第 8 周」，只看这一周；也能一键切到**学期总览**看全学期
- **导出 PDF**：手机版按周**保证一页**，直接打印或交作业
- **导出图片**：2 倍分辨率 PNG，发群里、发同学都看得清
- **发到手机**：单文件、不联网，微信发给谁都能双击打开；真机上自动铺满屏幕

**和现在你用的办法比：**

| | 手写 / Excel | 截图课表 | 学校教务系统 | 这个 skill |
|---|---|---|---|---|
| 需要你做的事 | 一格一格填 | 找别人要 | 登录、找导出 | **说一遍** |
| 改一门课 | 重排、重画 | 重截 | 回系统改 | **说一句"周四那门挪到周五"** |
| 只看某一周 | 自己数周次 | 做不到 | 不一定有 | **下拉框选** |
| 离线 / 发人 | 文件能发 | 图片能发 | 常常要登录 | **单文件 HTML，双击即看** |
| 手机上看 | 挤 | 糊 | 要装 App | **手机版布局** |

---

## 特性

- **两种看法**：按周查看（下拉选第 N 周）｜学期总览（全学期汇总，同格多课叠放、各带周次）
- **两种形态**：电脑版（横版表格）｜手机版（手机外观 + 按天卡片；真机 ≤560px 自动铺满屏幕）
- **两种导出**：PDF（纸张尺寸跟着当前状态走，手机版按周**保证一页**）｜PNG（纯 SVG→Canvas，2 倍分辨率，无外部库）
- **单文件、离线**：产物不联网、无外部资源、双击就能看，可以直接发群里
- **周次语法**：`8-16`、`9-17、19-21`、`8-16单` / `8-16双`、`8`，中文数字与「到 / 至 / ～」也认
- **语音输入**：语音转写成文字后同样能解析 —— skill 看不懂音频，但 agent 拿到转写结果就能用
- **改课便宜**：过几天说「把历史学专题从周四 3-4 改到周五 3-4」，它反解出原数据，只改那一条
- **不覆盖你的文件**：输出文件名自动避让（已有 `课表.html` → 生成 `课表2.html`）
- **隐私默认值**：不写姓名（除非你明确要求）、不写年级 / 班级、不设 `title` 字段

### 为什么它的课表是可信的（简单说）

课表的错是**静默**的 —— 周次写成 8-16 还是 8-15、课程名少一个字，页面照样好看、照样能导出、照样能打印，
你要到开学第三周才发现。所以生成过程中有三道拦截：

| 拦截 | 做什么 |
|---|---|
| 冲突探测 | 同一周、同一天、同一节次段里撞了两门课 → **拒绝生成**，先回来问你 |
| 自动自检 | 逐字段比对 `spec` 与页面、逐周展开检查、用页面真实的脚本跑一遍 UI 断言 |
| 独立核对 | 另派一个**没看过中间数据**的 agent 重新解析你的原话，逐条对撞后才交付 |

---

## 快速开始

没装过 skill？三步：

**① 下载**

```bash
git clone https://github.com/FranciscoLaurent/course-timetable-skill.git
```

**② 放进你的 agent 的 skills 目录**

把整个目录拷进去（目录名保持 `course-timetable`）：

| 你的 agent | 放这里 |
|---|---|
| Claude Code 等 | `~/.claude/skills/course-timetable/` |
| 其它 agent | 对应的 skills 目录，例如 `~/.agents/skills/course-timetable/` |

只要目录里有 `SKILL.md` 就会被识别，不用改配置。

**③ 对 agent 说**

> 「帮我做个课表：我周一周三 5-7 节上硕士英语，周二周四 1-2 节机器学习」

agent 会自动读 `SKILL.md`，按里面的流程解析、查冲突、生成、自检，然后把 `课表.html` 交给你。

**依赖**：Python 3（只用标准库）**必需**；Node 与 Chrome / Edge / Chromium / Firefox **可选**，缺了会自动降级
（降级了会在交付消息里告诉你，不会假装验过）。

---

## 不用 agent，当命令行工具用

```bash
# 1) 写一份 spec.json（格式见下）
# 2) 探测冲突（只检测，不写任何文件）
python scripts/build_timetable.py spec.json --detect

# 3) 生成（文件名自动避让，绝不覆盖既有文件）
python scripts/build_timetable.py spec.json

# 4) 自检
python scripts/check_timetable.py spec.json "课表.html"
node   scripts/render_weeks.js    "课表.html"
python scripts/verify_visual.py   "课表.html"     # 可选：真浏览器渲染 + 量几何

# 5) 改课：从已有页面反解回 spec.json
python scripts/spec_from_html.py  "课表.html" spec.json
```

| 参数 | 作用 |
|---|---|
| `--detect` | 只探测冲突，不写文件 |
| `--force` | 覆盖同名输出（默认不覆盖，自动改叫 `课表2.html`） |
| `--allow-conflict` | 明知冲突仍要生成（确认「就是这么排的、两门都要」时才用，冲突格会叠放显示） |

### spec.json

```json
{
  "term": "2026 秋",
  "days": ["周一", "周二", "周三", "周四", "周五"],
  "blocks": ["1-2", "3-4", "5-8", "9-10"],
  "courses": [
    {"day":"周一","block":"1-2","name":"高等数学","room":"教三-201","teacher":"李老师","weeks":"8-16"},
    {"day":"周三","block":"5-8","name":"大学物理","room":"体育馆一层","weeks":"9-14、19-21"},
    {"day":"周五","block":"9-10","name":"专业英语","weeks":"8-16双"}
  ]
}
```

| 字段 | 说明 |
|---|---|
| `days` | 一周上几天（默认周一到周日全显示，周末当"有课"处理） |
| `blocks` | 节次段，就是表格的行；顺序即显示顺序，段长可以不等（默认 `["1-2","3-4","5-7","8-10"]`） |
| `room` / `teacher` | 可缺；两个都没有时页面上那一行自动省略 |
| `who` | **默认不写**（标题就是「第8周课表」）；只有你明确要求才加 |
| `hideEmptyDays` | 默认 `false`（7 天全显示）；设 `true` 则整周没课的那天不显示 |
| `term` | 只填学期（`2026 秋`），不要填 `2026级` |
| `minWeek` / `maxWeek` / `defaultWeek` | 可选，脚本会校验它们与课程周次不矛盾 |

> 课程里的 `block` 必须**逐字**等于 `blocks` 里的某一项，否则脚本直接报错 —— 这是有意的：
> 宁可报错，也不要排到错误的行上。

---

## 页面怎么用

- **切看法**：左上角「按周查看 / 学期总览」；切周次可以用下拉框、「上一周 / 下一周」按钮，或键盘 `←` `→`
- **切形态**：右上角「电脑版 / 手机版」，默认按屏幕宽度自动选，手动切过会记住
- **导出 PDF**：点「导出 PDF」调起打印对话框，把「目标打印机」选成「另存为 PDF」
  （浏览器不允许网页直接生成 PDF，只能走打印；页面上会提示这一步）
- **导出图片**：点「导出图片」直接下载 PNG；当前是什么状态就导什么
- **地址栏可分享状态**：`?week=9&view=mobile&scope=overview`

---

## 目录结构

```
├── SKILL.md                        给 agent 的说明书（工作流 + 硬规则）
├── test-prompts.json               典型使用场景的测试 prompt
├── assets/timetable.template.html  网页模板
├── scripts/
│   ├── build_timetable.py          spec.json → HTML；同时是冲突检测器（--detect）
│   ├── check_timetable.py          spec ↔ HTML 一致性 / 逐周展开 / 冲突检查
│   ├── render_weeks.js             用页面真实脚本渲染 + UI 断言（DOM 桩）
│   ├── verify_visual.py            可选：真浏览器渲染 + 量几何（没有浏览器降级成人工清单）
│   └── spec_from_html.py           课表.html → spec.json（要改课表时把数据捞回来）
├── references/                     解析规则 / 核对 prompt / 页面说明 / 踩坑记录
├── tests/                          自检套件（205 项）+ 两个示例 spec
└── docs/                           预览图
```

---

## 常见问题

**要装 Python 库吗？**
不用。Python 3 只用标准库。Node 和浏览器是可选增强，缺了会跳过对应校验并如实告诉你。

**生成的网页要联网吗？会不会加载不出来？**
不联网，没有任何外部资源，双击就开。可以直接微信 / 邮件发给别人。

**能识别语音吗？**
skill 本身不处理音频。你用带语音输入的 agent（或先把语音转成文字）把课程信息说出来，转写后的文字就是它的输入。

**教室和老师没说行不行？**
行。可缺，页面上那一行会自动省略，不会留空行。交付后 agent 还会补问一句要不要加上。

**课表会不会带上我的名字？**
默认不带，标题就是「第8周课表」。你说「写上我的名字」才会加。

**能改吗？**
能。说「把历史学专题从周四 3-4 改到周五 3-4」，它会从页面反解出数据，只改那一条再重新生成，
仍然不覆盖旧文件（除非确认那是上一次的产物）。

**周末一定要显示吗？**
默认 7 天全显示，因为不少学校周末有课。你说一句「我们周末没课」就收掉。

---

## 自检

改过脚本 / 模板之后跑一遍：

```bash
python tests/run_tests.py      # 结果: 205 通过 / 0 失败
```

## License

[MIT](LICENSE)
