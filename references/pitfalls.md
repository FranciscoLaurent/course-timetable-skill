# 改这个 skill 时的禁忌与历史教训

**日常做课表不需要读这份文件。** 这里记录的全是"改 `scripts/` 或 `assets/` 才会踩"的坑 ——
每一条都是真踩过的，多数已经被 `tests/run_tests.py` 用断言钉住了。

---

## 1. 模板 / 渲染

| 坑 | 现象 | 正确做法 |
|---|---|---|
| 周次显示层重复拼「周」 | 「第 8-16周 周」；**CLI 摘要行也曾犯**（`第 8-16 单周 周`） | 数据层存归一化文本（`weeksText`），显示层用 **`weeksLabel`**，不要再拼一次「周」 |
| 空周分支提前 return | 空周时下拉框/按钮与页面不同步 | 同步代码放在早退**之前** |
| 周末底色按列序号判断 | 自定义列顺序/天数时底色错位 | 按星期名判断（`isWeekend()`），别改回去 |
| 视图只改一边 | 电脑版调好了，手机版还是旧的 | 改渲染逻辑后跑 `render_weeks.js`，它断言两版**内容/教室/教师**必须一致 |
| 机身高度用 `max-height:100%` | **手机下沿被屏幕底边裁掉**：百分比高度对"由 flex 撑出来的不确定高度"解析失败，机身永远 844px 直接溢出 | 机身容器 `flex-direction:column` + `.phone{flex:0 1 844px;min-height:0}` 让它能被压短；容器留 `padding:16px` 给 11/12px 的 box-shadow 外框 |
| 在 `.bar` 里塞太多东西（窄屏） | 真机上按钮被挤出屏幕 | ≤560px 隐藏无用的键盘提示、统计与按钮换行居中 |
| 单周课表文案 | 「第 8 ~ 8 周」 | 用 `span_text(lo, hi)`，相等时输出「第 8 周」 |

## 2. 怎么验"看起来对不对"

| 坑 | 现象 | 正确做法 |
|---|---|---|
| 用无头浏览器直接截窄屏图 | **会被最小窗口宽度骗到**：Chrome 的窗口最窄约 526px，给 `--window-size=390` 它按 526px 排版再把图裁成 390 宽 —— 右边看着"被切了"，其实页面根本没溢出 | 用**固定宽度的 iframe**承载页面（`verify_visual.py` 就是这么做的），并且**以 `documentElement.scrollWidth ≤ innerWidth` 为准**，不要只看截图 |
| 只看文本断言 | 布局类的坑文本断言根本看不见 | 有浏览器就跑 `verify_visual.py`；它默认只量不存图，`--all` 跑 5 档，`--shot` 才出图 |
| 把"可滚动长页"当成"被裁" | 真机模式页面本来就有 1000+px 高 | 机身是否被裁只在**固定舞台**（页面不可滚动）时才判定 —— `scrollHeight > innerHeight` 就是长页，别报越界 |

## 3. 数据流 / 字段

| 坑 | 现象 | 正确做法 |
|---|---|---|
| `maxWeek` 小于课程实际最晚周次 | **后半学期的课被静默吃掉**，而 build/check/render 三套检查全绿 | `build_timetable.py` 已加交叉校验（`maxWeek < 实际最晚周` 直接报错） |
| `defaultWeek` 越界 | 打开就是一张空表，下拉框里还没这一项 | 已加范围校验 |
| 反解丢字段 | `spec_from_html.py` 曾经丢掉 `minWeek/maxWeek/defaultWeek`，重新生成后周次下拉从 21 项变 9 项 | 反解必须把这三个字段一起还原；`run_tests.py` 第 9 节有往返断言 |
| spec 带 BOM | Windows 记事本另存会加 BOM，`json.load` 直接抛 `JSONDecodeError` | 读 spec 一律 `encoding='utf-8-sig'` |
| 课程名含 `</script>` | 注入的 JSON 提前闭合页面脚本，产物被截断，`check` 还报"全部通过" | 注入前把 `<` 转成 `\u003c`（JSON 里等价，`json.loads` 能还原） |
| `minWeek` | 曾经是**全链路死字段**：写进 DATA、模板 0 处引用 | 现在只影响摘要与跨度文案；若要让页面也用，得同时改 `fillWeekSelect`/`buildWeekMap` |

## 4. 自检套件本身

| 坑 | 现象 | 正确做法 |
|---|---|---|
| 假断言 | `all((x or y) or True for ...)` 恒真；"有可读报错"的判据对 traceback 也成立 | 断言要写"会失败"的版本；第 9 节专门放了负向测试（篡改 HTML 后 `check` 必须非 0） |
| **子串判据当等值判据** | `render_weeks.js` 里 `stat.includes(String(n))` 曾被当作"统计行与卡片数相符"——可统计行是「本周共 N 门次课，占用 M 个时段」，**两个数字互相掩护**（"共 12 门次"里的 "2" 能让 n=2 通过），门次==时段时恒真。实测把 `weekStats` 的 count +1 后，render 退出码 0、205 项自检全绿 | 把数字**解析出来精确比较**（`/共\s*(\d+)\s*门次课/`）；并在 `run_tests.py` 里加一条**变异测试**：改坏 `weekStats` 后 render 必须失败，否则这条断言随时会再变回死的 |
| 格式脆断言 | 模板里 `padding:16px` 改成 `padding: 16px`（纯格式）就红一条 | 存在性断言只用来锁"结构还在"；关键行为要有行为断言 |
| 没有 node 时的判断 | `subprocess` 找不到可执行文件是**抛异常**，不是返回 127 —— 旧判据 `returncode==127 / 'ENOENT' in stderr` 全是死的，表现为整套测试崩在 traceback 上 | 启动时用 `subprocess.run([NODE,'--version'])` 探测一次；没有就跳过渲染断言、退出码仍为 0 |
| 两份 DATA 提取器 | `run_tests.py` 里有两份朴素花括号计数，课程名含 `}` 时会崩 | 统一用 `check_timetable.extract_data` |
| stderr 编码 | 中文 Windows 上 stderr 是 GBK，`✗` 被 backslashreplace 成字面 `\u2717` | 子进程统一 `PYTHONIOENCODING=utf-8`；断言同时兼容两种形态（`'✗'.encode('gbk')` 会直接抛异常，别这么写） |
| `__pycache__` | 跑完测试在 skill 目录里留下 `.pyc`，打包带出去 | 三个 import 方都设 `sys.dont_write_bytecode = True`（顺序必须在 import 之前） |
| 临时产物 | 测试往 skill 目录写临时文件（skill 常是只读资源） | 一律写系统临时目录，跑完 `shutil.rmtree` |

## 5. 交付与文件

| 坑 | 现象 | 正确做法 |
|---|---|---|
| 覆盖既有文件 | 换个用户/换学期直接盖掉别人已有的课表 | `unique_out_path()`：重名自动 `课表2.html`；`spec_from_html.py` 同样不覆盖 |
| 未知开关被当文件名 | `--detectt` 笔误生成一个叫 `--detectt` 的文件 | 已加未知参数校验 |
| 输出路径是目录 | 静默写出一个无扩展名文件 | 已加目录校验 |
| 打包给别人前 | 可能带上用户数据 | 先 `grep -r` 搜课程名/姓名/年级 |

---

改完记得跑一次：

```bash
python "<SKILL>/tests/run_tests.py"
```
