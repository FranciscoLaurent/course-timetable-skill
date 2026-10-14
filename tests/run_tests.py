# -*- coding: utf-8 -*-
"""
course-timetable skill 自检套件。

用法（在任意目录）:
    python <SKILL>/tests/run_tests.py

覆盖三部分：
  1. 周次解析（阿拉伯数字 / 中文数字 / 单双周 / 多段 / 全角）
  2. 错误处理（坏 spec 必须报错，而不是静默生成错表）
  3. 端到端（build → check → render 三个脚本都要退出码 0）

Node 不是必需：未找到 node 时自动跳过渲染检查（启动时探测一次）。
"""
import sys, os, json, re, glob, shutil, subprocess, tempfile

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.abspath(os.path.join(HERE, os.pardir))
SCRIPTS = os.path.join(SKILL, 'scripts')


def make_out_dir():
    """临时产物绝不能写进 skill 目录 —— skill 目录通常是只读资源。
    依次尝试系统临时目录、当前工作目录，用"真写一个探针文件"来判定是否可写
    （有些受限环境允许建目录但不允许写入）。"""
    candidates = []
    try:
        candidates.append(tempfile.mkdtemp(prefix='course_timetable_test_'))
    except Exception:
        pass
    candidates.append(os.path.join(os.getcwd(), '_course_timetable_test'))
    for d in candidates:
        try:
            os.makedirs(d, exist_ok=True)
            probe = os.path.join(d, '.write_probe')
            with open(probe, 'w', encoding='utf-8') as f:
                f.write('ok')
            os.remove(probe)
            return d
        except Exception:
            continue
    raise SystemExit('✗ 找不到可写目录存放测试产物（已试过系统临时目录与当前目录）')


OUT = make_out_dir()
sys.path.insert(0, SCRIPTS)
sys.dont_write_bytecode = True          # 别在 skill 目录里留下 __pycache__
from build_timetable import parse_weeks, to_ranges, span_text, SpecError  # noqa: E402
from check_timetable import extract_data                                  # noqa: E402

PY = sys.executable
NODE = os.environ.get('NODE_BIN', 'node')
BUILD = os.path.join(SCRIPTS, 'build_timetable.py')
SPEC_FROM_HTML = os.path.join(SCRIPTS, 'spec_from_html.py')
CHECK = os.path.join(SCRIPTS, 'check_timetable.py')
RENDER = os.path.join(SCRIPTS, 'render_weeks.js')
# 子进程一律用 UTF-8 输出：否则中文 Windows 上 stderr 是 GBK，✗ 会被 backslashreplace
# 成字面 `\u2717`，上层按 UTF-8 解码就是乱码，断言也没法写。
SUBENV = dict(os.environ, PYTHONIOENCODING='utf-8')
ERR_MARKS = ('✗'.encode('utf-8'), b'\\u2717')   # 兼容没带 UTF-8 环境变量的情况


def probe_node():
    """启动时探测一次 node。注意：subprocess 找不到可执行文件是**抛异常**，
    不是返回 127 —— 旧代码用 returncode==127 / 'ENOENT' in stderr 判断，
    三个条件全是死的，于是"没有 node 就跳过"实际表现成整套测试崩在 traceback 上。"""
    try:
        subprocess.run([NODE, '--version'], capture_output=True, timeout=30)
        return True
    except Exception:
        return False


node_ok = probe_node()  # 找到 node 才跑渲染相关断言
if not node_ok:
    print(f'  – 未找到 node（{NODE}），本次跳过全部渲染断言；设 NODE_BIN 可指定路径')
passed = failed = 0


def ok(name, cond, detail=''):
    global passed, failed
    if cond:
        passed += 1
        print(f'  ✓ {name}')
    else:
        failed += 1
        print(f'  ✗ {name}   {detail}')


print('=' * 72)
print('1. 周次解析（阿拉伯数字 / 中文数字 / 单双周 / 多段）')
print('=' * 72)
CASES = [
    ('8-16',                set(range(8, 17)),                       '8-16'),
    ('第8～16周',            set(range(8, 17)),                       '8-16'),
    ('八到十六周',           set(range(8, 17)),                       '8-16'),
    ('第9~17周、第19~21周',  set(range(9, 18)) | set(range(19, 22)),  '9-17、19-21'),
    ('8-16单',              {9, 11, 13, 15},                         '8-16 单周'),
    ('8-16双',              {8, 10, 12, 14, 16},                     '8-16 双周'),
    ('第8周',               {8},                                     '8'),
    ('十到十二周',           {10, 11, 12},                            '10-12'),
    ('第二十一周',           {21},                                    '21'),
    ('8、10、12周',          {8, 10, 12},                             '8、10、12'),
    ('８-１６',              set(range(8, 17)),                       '8-16'),
    ('8至16周',             set(range(8, 17)),                       '8-16'),
]
for raw, want_set, want_text in CASES:
    try:
        ws, wt = parse_weeks(raw, 'test')
        ok(f'{raw!r} → {sorted(ws)}',
           ws == want_set and wt == want_text,
           f'实得 set={sorted(ws)} text={wt!r}；期望 set={sorted(want_set)} text={want_text!r}')
    except SpecError as e:
        ok(f'{raw!r} → 解析成功', False, f'抛错: {e}')

ok('to_ranges 压缩连续区间', to_ranges({8, 9, 10, 13, 14}) == [[8, 10], [13, 14]],
   str(to_ranges({8, 9, 10, 13, 14})))

print()
print('=' * 72)
print('2. 错误处理（坏 spec 必须报错，不能静默生成错表）')
print('=' * 72)
BAD = [
    ('缺 weeks',         {'courses': [{'day': '周一', 'block': '1-2', 'name': 'A'}]}),
    ('周次无法解析',      {'courses': [{'day': '周一', 'block': '1-2', 'name': 'A', 'weeks': 'abc'}]}),
    ('周次区间颠倒',      {'courses': [{'day': '周一', 'block': '1-2', 'name': 'A', 'weeks': '16-8'}]}),
    ('block 不在块列表',  {'courses': [{'day': '周一', 'block': '9-11', 'name': 'A', 'weeks': '1-2'}]}),
    ('day 不在天列表',    {'courses': [{'day': '周八', 'block': '1-2', 'name': 'A', 'weeks': '1-2'}]}),
    ('课程名为空',        {'courses': [{'day': '周一', 'block': '1-2', 'name': '', 'weeks': '1-2'}]}),
    ('courses 为空',      {'courses': []}),
]
shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT, exist_ok=True)
for i, (name, spec) in enumerate(BAD):
    td = os.path.join(OUT, str(i))
    os.makedirs(td, exist_ok=True)
    sp = os.path.join(td, 's.json')
    with open(sp, 'w', encoding='utf-8') as f:
        json.dump(spec, f, ensure_ascii=False)
    r = subprocess.run([PY, BUILD, sp, os.path.join(td, 'o.html')], capture_output=True, env=SUBENV)
    ok(f'{name} → 退出码非 0', r.returncode != 0, f'退出码={r.returncode}')
    ok(f'{name} → 报错可读（不是裸 traceback）',
       b'Traceback' not in r.stderr and any(m in r.stderr for m in ERR_MARKS),
       r.stderr.decode('utf-8', 'replace')[:90])

print()
print('=' * 72)
print('3. 端到端（生成 → 核对 → 渲染）')
print('=' * 72)
spec_path = os.path.join(HERE, 'spec.example.json')
out_html = os.path.join(OUT, 'example.html')
if os.path.exists(out_html):        # 上一次跑崩了会留下旧文件，先清掉再生成
    os.remove(out_html)
for name in ('build_timetable.py', 'check_timetable.py'):
    r = subprocess.run([PY, os.path.join(SCRIPTS, name), spec_path, out_html], capture_output=True)
    ok(f'{name} 退出码 0', r.returncode == 0, r.stdout.decode('utf-8', 'replace')[-300:])

if node_ok:
    r = subprocess.run([NODE, RENDER, out_html], capture_output=True)
    ok('render_weeks.js 退出码 0', r.returncode == 0, r.stdout.decode('utf-8', 'replace')[-400:])

# 顺手确认生成的 HTML 里没有残留占位符
if os.path.exists(out_html):
    html = open(out_html, encoding='utf-8').read()
    ok('生成的 HTML 无 __DATA__ 残留', '__DATA__' not in html)

print()
print('=' * 72)
print('4. 手机版 / 视图切换')
print('=' * 72)
if os.path.exists(out_html):
    html = open(out_html, encoding='utf-8').read()
    for needle, label in (
        ('id="viewWeb"', '电脑版按钮'),
        ('id="viewMobile"', '手机版按钮'),
        ('id="scopeWeek"', '「按周查看」按钮'),
        ('id="scopeAll"', '「学期总览」按钮'),
        ('function renderScope', '按范围渲染函数'),
        ('var OVERVIEW', '学期总览数据（同格多课合并）'),
        ('body.mode-overview td{height:auto', '总览时行高由内容撑开'),
        ('function chooseScope', '范围切换函数'),
        ('function overviewTitle', '总览标题函数'),
        ('id="mlist"', '手机版内容容器'),
        ('body.view-mobile', '手机版样式'),
        ('renderMobileView', '手机版渲染函数'),
        ('class="phone"', '手机机身'),
        ('class="phoneNotch"', '手机灵动岛'),
        ('id="pWeek"', '手机内周次下拉'),
        ('id="pPrev"', '手机内上一周'),
        ('id="pNext"', '手机内下一周'),
        ('id="pTitle"', '手机内标题'),
        ('class="stageInk"', '背景天地字容器'),
        ('>课</span>', '背景「课」字'),
        ('>表</span>', '背景「表」字'),
        ('class="hint barHint"', '顶栏的周次切换提示'),
        ('body.view-mobile .barHint{display:inline}', '手机版显示该提示'),
        ('width:390px;height:844px', '机身尺寸 390×844（对齐参考）'),
        ('body.view-mobile .stageInk{display:block}', '舞台只在手机版出现'),
        ('rgba(31,78,216,.075)', '天地字用课表的蓝色调'),
        ('mask-image:radial-gradient(132% 106%', '坐标格向四周淡出'),
        ('body.view-mobile .foot,', '手机版隐藏页脚（腾高度给机身）'),
        ('max-width:560px', '真手机上的无边框适配'),
        ('body.view-mobile:not(.mode-overview) .printWrap{display:block', '按周手机版只印卡片图'),
    ):
        ok(f'模板含{label}', needle in html)

    # 页面上不得出现"2026级 / 2班"这类建制标识
    BADGE = [r'\d+\s*级', r'\d+\s*班', r'[XxＸ]{1,4}\s*级', r'[XxＸ]{1,4}\s*班']
    hits = [m.group(0) for pat in BADGE for m in re.finditer(pat, html)]
    ok('无「XX级 / XX班」类标识', not hits, f'命中 {hits[:5]}')
    ok('数据里没有 title 字段（旧版用它放年级班级）', '"title"' not in re.search(r'const DATA = \{[\s\S]*?\n\};', html).group(0))

    def run_render(extra_env):
        env = dict(os.environ, **extra_env)
        return subprocess.run([NODE, RENDER, out_html, '--json'], capture_output=True, env=env)

    # 窄屏应默认手机版，宽屏应默认电脑版
    for width, want in ((400, 'mobile'), (1400, 'web')):
        if not node_ok:
            break
        r = run_render({'VIEW_WIDTH': str(width)})
        try:
            got = json.loads(r.stdout.decode('utf-8'))['initialView']
            ok(f'屏宽 {width}px → 默认「{want}」', got == want, f'实得 {got}')
        except Exception as e:
            ok(f'屏宽 {width}px → 默认「{want}」', False, str(e)[:80])

    if node_ok:
        r = run_render({'VIEW_SEARCH': '?view=mobile', 'VIEW_WIDTH': '1400'})
        try:
            ok('?view=mobile 覆盖宽屏判断',
               json.loads(r.stdout.decode('utf-8'))['initialView'] == 'mobile')
        except Exception as e:
            ok('?view=mobile 覆盖宽屏判断', False, str(e)[:80])

        r = subprocess.run([NODE, RENDER, out_html, '8', '--mobile'],
                           capture_output=True, env=dict(os.environ))
        ok('--mobile 文本输出退出码 0', r.returncode == 0)
        ok('--mobile 输出含按天卡片', '┌' in r.stdout.decode('utf-8', 'replace'))

print()
print('=' * 72)
print('5. 不同学校作息适配')
print('=' * 72)


def build_variant(name, spec):
    """生成一个变体，返回 (是否成功, HTML 里的 DATA, 错误信息)"""
    d = os.path.join(OUT, 'v_' + name)
    os.makedirs(d, exist_ok=True)
    sp = os.path.join(d, 'spec.json')
    hp = os.path.join(d, 'out.html')
    with open(sp, 'w', encoding='utf-8') as f:
        json.dump(spec, f, ensure_ascii=False)
    r = subprocess.run([PY, BUILD, sp, hp, '--force'], capture_output=True)
    if r.returncode != 0:
        return False, None, r.stderr.decode('utf-8', 'replace')[:160]
    html = open(hp, encoding='utf-8').read()
    data = extract_data(html)          # 与 check_timetable 共用同一份解析（认字符串/转义）
    if node_ok:
        rr = subprocess.run([NODE, RENDER, hp], capture_output=True)
        if rr.returncode != 0:
            return False, data, rr.stdout.decode('utf-8', 'replace')[-200:]
    return True, data, ''


C = [{'day': '周一', 'block': '1-2', 'name': '高等数学', 'weeks': '1-16'},
     {'day': '周三', 'block': '3-4', 'name': '大学物理', 'weeks': '1-16'}]

# ① 五天制：一周只上周一到周五，压根不存在周末
okr, d, err = build_variant('a', {'who': '甲', 'days': ['周一', '周二', '周三', '周四', '周五'], 'courses': C})
ok('五天制：生成成功', okr, err)
ok('五天制：只有 5 列且不含周六', bool(d) and d['days'] == ['周一', '周二', '周三', '周四', '周五'], str(d and d['days']))

# ② 下午连排 5-8、晚上 9-10（共 4 段，段长不等）
okr, d, err = build_variant('b', {'who': '乙', 'blocks': ['1-2', '3-4', '5-8', '9-10'], 'courses': C})
ok('下午 5-8 / 晚上 9-10：生成成功', okr, err)
ok('独立节次段生效', bool(d) and d['blocks'] == ['1-2', '3-4', '5-8', '9-10'], str(d and d['blocks']))

# ③ 一天六段：上午两段 + 下午两段 + 晚上两段
okr, d, err = build_variant('c', {'who': '丙', 'blocks': ['1-2', '3-4', '5-6', '7-8', '9-10'], 'courses': C})
ok('一天 5 段（下午分 5-6 / 7-8）：生成成功', okr, err)
ok('5 个节次段全部保留', bool(d) and len(d['blocks']) == 5, str(d and d['blocks']))

# ④ 有周末作息但整周没课：hideEmptyDays 自动去掉空白天
okr, d, err = build_variant('d', {'who': '丁', 'hideEmptyDays': True,
                                  'days': ['周一', '周二', '周三', '周四', '周五', '周六', '周日'],
                                  'courses': [{'day': '周一', 'block': '1-2', 'name': '高等数学', 'weeks': '1-16'},
                                              {'day': '周五', 'block': '3-4', 'name': '大学物理', 'weeks': '1-16'}]})
ok('hideEmptyDays：生成成功', okr, err)
if node_ok and okr:
    hp = os.path.join(OUT, 'v_d', 'out.html')
    rr = subprocess.run([NODE, RENDER, hp, '1', '--json'],
                        capture_output=True, env=dict(os.environ, VIEW_WIDTH='1400'))
    js = json.loads(rr.stdout.decode('utf-8'))
    wk = js['weeks'][0]
    ncol = len(wk['rows'][0]['cells']) if wk['rows'] else 0
    ok('hideEmptyDays：渲染后只剩 2 列（周一、周五）', ncol == 2, f'实得 {ncol} 列')

# ⑤ 段位写错必须报错，而不是默默排错
okr, d, err = build_variant('e', {'who': '戊', 'blocks': ['1-2', '3-4', '5-8', '9-10'],
                                  'courses': [{'day': '周一', 'block': '5-7', 'name': '高等数学', 'weeks': '1-16'}]})
ok('节次落在定义之外 → 报错', not okr, err)

# ⑥ 文档里那份"非默认作息"示例必须真的能跑通（不然文档就是错的）
ex5 = os.path.join(HERE, 'spec.example-5day.json')
with open(ex5, encoding='utf-8') as f:
    ex5_spec = json.load(f)
okr, d, err = build_variant('f', ex5_spec)
ok('spec.example-5day.json 能跑通', okr, err)
ok('示例 2：只有 5 列', bool(d) and len(d['days']) == 5, str(d and d['days']))
ok('示例 2：分段为 1-2 / 3-4 / 5-8 / 9-10',
   bool(d) and d['blocks'] == ['1-2', '3-4', '5-8', '9-10'], str(d and d['blocks']))

# ⑦ 默认行为：不写配置时，一周 7 天全显示（周末默认"有课"）
okr, d, err = build_variant('g', {'who': '己',
                                  'courses': [{'day': '周一', 'block': '1-2', 'name': '高等数学', 'weeks': '1-16'},
                                              {'day': '周三', 'block': '3-4', 'name': '大学物理', 'weeks': '1-16'}]})
ok('不写任何配置也能生成', okr, err)
ok('hideEmptyDays 默认关闭（周末默认显示）',
   bool(d) and d.get('hideEmptyDays') is False, str(d and d.get('hideEmptyDays')))
if node_ok and okr:
    hp = os.path.join(OUT, 'v_g', 'out.html')
    rr = subprocess.run([NODE, RENDER, hp, '1', '--json'],
                        capture_output=True, env=dict(os.environ, VIEW_WIDTH='1400'))
    js = json.loads(rr.stdout.decode('utf-8'))
    wk = js['weeks'][0]
    ncol = len(wk['rows'][0]['cells']) if wk['rows'] else 0
    ok('默认 7 列全显示（周六周日保留）', ncol == 7, f'实得 {ncol} 列')

# ⑧ 用户说"我们周末没课"时，才关掉空白天
okr, d, err = build_variant('h', {'who': '庚', 'hideEmptyDays': True,
                                  'courses': [{'day': '周一', 'block': '1-2', 'name': '高等数学', 'weeks': '1-16'}]})
ok('hideEmptyDays=true 生效', bool(d) and d.get('hideEmptyDays') is True, str(d and d.get('hideEmptyDays')))
if node_ok and okr:
    hp = os.path.join(OUT, 'v_h', 'out.html')
    rr = subprocess.run([NODE, RENDER, hp, '1', '--json'],
                        capture_output=True, env=dict(os.environ, VIEW_WIDTH='1400'))
    js = json.loads(rr.stdout.decode('utf-8'))
    wk = js['weeks'][0]
    ncol = len(wk['rows'][0]['cells']) if wk['rows'] else 0
    ok('周末没课时只显示有课的 1 列', ncol == 1, f'实得 {ncol} 列')

# ⑨ 教室 / 教师：给了就显示，没给就整行省略
okr, d, err = build_variant('i', {'who': '辛',
                                  'courses': [{'day': '周一', 'block': '1-2', 'name': '高等数学',
                                               'room': '教三-201', 'teacher': '李老师', 'weeks': '1-16'},
                                              {'day': '周二', 'block': '1-2', 'name': '大学物理',
                                               'room': '教三-105', 'weeks': '1-16'},
                                              {'day': '周三', 'block': '1-2', 'name': '线性代数',
                                               'weeks': '1-16'}]})
ok('教室/教师可缺省：生成成功', okr, err)
if okr and d:
    c0, c1, c2 = d['courses']
    ok('给了教师 → 保留', c0.get('teacher') == '李老师', str(c0.get('teacher')))
    ok('只给教室 → 教师为空', c1.get('teacher') == '' and c1.get('room') == '教三-105', str(c1))
    ok('都不给 → 两个都为空', c2.get('teacher') == '' and c2.get('room') == '', str(c2))
if node_ok and okr:
    hp = os.path.join(OUT, 'v_i', 'out.html')
    rr = subprocess.run([NODE, RENDER, hp, '1', '--json'],
                        capture_output=True, env=dict(os.environ, VIEW_WIDTH='1400'))
    js = json.loads(rr.stdout.decode('utf-8'))
    wk = js['weeks'][0]
    cells = [c for row in wk['rows'] for c in row['cells']]
    flat = [c for cs in cells for c in cs]
    ok('网页里显示出教师', any(c.get('teacher') == '李老师' for c in flat), str([c.get('teacher') for c in flat]))
    ok('网页里教室正确', any(c.get('room') == '教三-105' for c in flat), str([c.get('room') for c in flat]))
    linalg = [c for c in flat if c.get('name') == '线性代数']
    ok('两样都没给的那门课：教室/教师都为空（页面会自动省略那一行）',
       bool(linalg) and all(not c.get('room') and not c.get('teacher') for c in linalg),
       str(linalg))
    ok('HTML 里没有空的教室/教师容器', '<div class="croom"></div>' not in html)
    ok('给了教室的课确实渲染出 croom', 'croom' in html)

# ⑩ 标题默认不带姓名（用户不会主动说名字，也别去猜）
okr, d, err = build_variant('j', {'courses': C})
ok('不写 who 也能生成', okr, err)
ok('who 默认为空（标题不带姓名）', bool(d) and d.get('who') == '', repr(d and d.get('who')))
if node_ok and okr:
    hp = os.path.join(OUT, 'v_j', 'out.html')
    rr = subprocess.run([NODE, RENDER, hp, '1', '--json'],
                        capture_output=True, env=dict(os.environ, VIEW_WIDTH='1400'))
    js = json.loads(rr.stdout.decode('utf-8'))
    t = js['weeks'][0]['title']
    ok('标题 = 「第1周课表」（无姓名、无前导空格）', t == '第1周课表', repr(t))
    ok('总览标题 = 「学期课表总览」', js.get('overviewTitle') == '学期课表总览', repr(js.get('overviewTitle')))

# ⑪ 用户明确要求时才带姓名；姓名里的「（2026级）」这类尾巴自动去掉
okr, d, err = build_variant('k', {'who': ' 甲（2026级）', 'courses': C})
ok('who 带建制尾巴也能生成', okr, err)
ok('who 清洗成「甲」（去掉括号尾巴与首尾空格）', bool(d) and d.get('who') == '甲', repr(d and d.get('who')))
if node_ok and okr:
    hp = os.path.join(OUT, 'v_k', 'out.html')
    rr = subprocess.run([NODE, RENDER, hp, '1', '--json'],
                        capture_output=True, env=dict(os.environ, VIEW_WIDTH='1400'))
    js = json.loads(rr.stdout.decode('utf-8'))
    t = js['weeks'][0]['title']
    ok('带姓名时标题 = 「甲第1周课表」', t == '甲第1周课表', repr(t))
    ok('带姓名时总览标题 = 「甲学期课表总览」', js.get('overviewTitle') == '甲学期课表总览', repr(js.get('overviewTitle')))

print()
print('=' * 72)
print('6. 导出（PDF / 图片）')
print('=' * 72)
if os.path.exists(out_html):
    html = open(out_html, encoding='utf-8').read()
    for needle, label in (
        ('id="pdfBtn"', '「导出 PDF」按钮'),
        ('id="imgBtn"', '「导出图片」按钮'),
        ('id="toast"', '提示条'),
        ('function exportPDF', 'PDF 导出函数'),
        ('function exportImage', '图片导出函数'),
        ('function buildTableSVG', '电脑版 SVG 生成器'),
        ('function buildCardsSVG', '手机版 SVG 生成器'),
        ("'data:image/svg+xml;charset=utf-8,'", 'SVG→data URL'),
        ('toBlob', 'Canvas 导出 PNG'),
    ):
        ok(f'模板含{label}', needle in html)
    ok('打印时隐藏导出按钮', '.ctrl,.viewToggle,.btn.sm' in html)
    for needle, label in (
        ('id="pageStyle"', '动态纸张尺寸容器'),
        ('function setPrintPage', '打印纸张设定函数'),
        ('id="printWrap"', '手机版打印用图容器'),
        ('body.view-mobile:not(.mode-overview) .printWrap{display:block', '按周手机版印同尺寸图'),
        ('body.view-mobile:not(.mode-overview) .phoneWrap{display:none!important}', '按周手机版隐藏机身'),
        ('body.view-mobile.mode-overview .phoneWrap{', '总览手机版印 HTML 卡片、允许多页'),
    ):
        ok(f'模板含{label}', needle in html)
    ok('页面不再显示生成时间', '生成时间' not in html)
    _db = re.search(r'const DATA = \{[\s\S]*?\n\};', html)
    ok('数据里也不再有 generated 字段', bool(_db) and '"generated"' not in _db.group(0))

    # ── 手机版机身下沿必须看得见 ──
    # 机身外框是 box-shadow 0 0 0 11px/12px 画的（画在盒子外面），且机身高度必须能被压短。
    # 曾经的写法是 .phoneWrap{padding:0;align-items:center}（横排）+ .phone{max-height:100%}：
    # max-height 的百分比要对着"高度确定的包含块"才解析，而这里的高度是 flex 撑出来的（不确定），
    # Chrome 判成 none → 机身永远 844px，在矮屏上溢出，被 body 的 overflow:hidden 裁掉下沿。
    ok('机身容器给外框留了空间（padding:16px）',
       'align-items:center;justify-content:center;padding:16px' in html)
    ok('机身高度靠 flex 自适应（可缩不可长）',
       'flex:0 1 844px' in html and 'height:844px;max-height:100%' not in html)
    ok('机身容器改成竖排（高度落在主轴上才能被压短）',
       'display:flex;flex-direction:column;\n    flex:1 1 auto;min-height:0;' in html)

    if node_ok:
        svgdir = os.path.join(OUT, 'svg')
        r = subprocess.run([NODE, RENDER, out_html, '--svg', svgdir],
                           capture_output=True, env=dict(os.environ))
        ok('SVG 生成退出码 0', r.returncode == 0, r.stdout.decode('utf-8', 'replace')[-200:])
        svgs = sorted(glob.glob(os.path.join(svgdir, '*.svg')))
        ok('生成了 2 个 SVG（表格 + 卡片）', len(svgs) == 2, str([os.path.basename(p) for p in svgs]))

        import xml.etree.ElementTree as ET
        for p in svgs:
            base = os.path.basename(p)
            try:
                tree = ET.parse(p)
                ok(f'{base} 是合法 XML', True)
            except Exception as e:
                ok(f'{base} 是合法 XML', False, str(e)[:120])
                continue
            root = tree.getroot()
            W, H = float(root.get('width')), float(root.get('height'))
            ok(f'{base} 尺寸合理', W > 100 and H > 100, f'{W}×{H}')
            texts = [(e.text or '') for e in root.iter() if e.tag.endswith('text')]
            body = ' '.join(texts)
            # 该周第一门课的名字必须画出来了
            first = None
            for c in json.load(open(spec_path, encoding='utf-8'))['courses']:
                if first is None:
                    first = c['name']
            ok(f'{base} 画出了课程名', first in body, f'找 {first!r}')
            ok(f'{base} 有周次标题', re.search(r'第\s*\d+\s*周', body) is not None, body[:60])
            # 几何不得越界
            bad = []
            for e in root.iter():
                def f(a):
                    try:
                        return float(e.get(a))
                    except (TypeError, ValueError):
                        return None
                x, y, w, h = f('x'), f('y'), f('width'), f('height')
                if x is not None and (x < -1 or x > W + 1):
                    bad.append(('x', x, e.tag))
                if y is not None and (y < -1 or y > H + 1):
                    bad.append(('y', y, e.tag))
                if x is not None and w is not None and x + w > W + 1:
                    bad.append(('x+w', x + w, e.tag))
                if y is not None and h is not None and y + h > H + 1:
                    bad.append(('y+h', y + h, e.tag))
            ok(f'{base} 无元素越界', not bad, str(bad[:4]))
            ok(f'{base} 无可疑占位符', 'undefined' not in body and 'NaN' not in body, body[:60])

print()
print('=' * 72)
print('7. 交付约定（自动命名 / 冲突探测 / 反解 / 文案）')
print('=' * 72)


def data_of(path):
    """取 HTML 里的 const DATA。直接用 check_timetable 的实现，别再维护第二份解析器。"""
    with open(path, encoding='utf-8') as f:
        return extract_data(f.read())


D7 = os.path.join(OUT, 'deliver')
os.makedirs(D7, exist_ok=True)
sp_ok, sp_bad, sp_one = (os.path.join(D7, n) for n in ('spec_ok.json', 'spec_bad.json', 'spec_one.json'))
with open(sp_ok, 'w', encoding='utf-8') as f:
    json.dump({'courses': C}, f, ensure_ascii=False)
with open(sp_bad, 'w', encoding='utf-8') as f:      # 与 C[0] 同天同段 → 必然冲突
    json.dump({'courses': C + [{'day': '周一', 'block': '1-2', 'name': '撞车课', 'weeks': '1-16'}]},
              f, ensure_ascii=False)
with open(sp_one, 'w', encoding='utf-8') as f:      # 全部只在第 8 周 → minWeek == maxWeek
    json.dump({'courses': [{'day': '周一', 'block': '1-2', 'name': '高等数学', 'weeks': '8'},
                           {'day': '周三', 'block': '3-4', 'name': '大学物理', 'weeks': '8'}]},
              f, ensure_ascii=False)


def run_build(*args):
    r = subprocess.run([PY, BUILD] + list(args), capture_output=True, cwd=D7)
    return r.returncode, (r.stdout.decode('utf-8', 'replace') + r.stderr.decode('utf-8', 'replace'))


def htmls():
    return sorted(f for f in os.listdir(D7) if f.endswith('.html'))


# ① 冲突探测：无冲突放行、有冲突拦住，两种情况都不写文件
code, out = run_build(sp_ok, '--detect')
ok('--detect 无冲突 → 退出码 0', code == 0, out[-160:])
ok('--detect 不写任何文件', htmls() == [], str(htmls()))
ok('--detect 明说不写文件', '没有写任何文件' in out)

code, out = run_build(sp_bad, '--detect')
ok('--detect 有冲突 → 退出码 1', code == 1, out[-160:])
ok('有冲突时不写文件', htmls() == [], str(htmls()))
ok('冲突提示要求先回去问用户', '先回去问用户' in out)
ok('冲突提示给了 --allow-conflict 出口', '--allow-conflict' in out)

# ② 默认输出名 = 课表.html
code, out = run_build(sp_ok)
ok('不带输出参数也能生成（自动起名）', code == 0, out[-160:])
ok('默认文件名 = 课表.html', os.path.exists(os.path.join(D7, '课表.html')), str(htmls()))
ok('输出行打印实际路径并标注交付对象', '课表.html' in out and '交付这个文件' in out)
first = open(os.path.join(D7, '课表.html'), encoding='utf-8').read()

# ③ 重名自动让开，绝不覆盖
code, out = run_build(sp_bad, '--allow-conflict')
ok('重名时自动改用 课表2.html', os.path.exists(os.path.join(D7, '课表2.html')), str(htmls()))
ok('让开时打印说明', '自动让开' in out)
ok('原有 课表.html 一个字节都没动',
   open(os.path.join(D7, '课表.html'), encoding='utf-8').read() == first)

# ④ --force 才允许覆盖
run_build(sp_bad, '--allow-conflict', '--force')
ok('--force 才会覆盖原文件',
   open(os.path.join(D7, '课表.html'), encoding='utf-8').read() != first)

# ⑤ 单周课表的文案（minWeek == maxWeek）
code, out = run_build(sp_one, '--detect')
ok('单周文案 = 「第 8 周」而不是「第 8 ~ 8 周」', '周次跨度 : 第 8 周（' in out, out[-200:])
ok('不再出现「第 8 ~ 8 周」', '第 8 ~ 8 周' not in out)
ok('span_text 单周/跨周都对', span_text(8, 8) == '第 8 周' and span_text(8, 16) == '第 8 ~ 16 周')

# ⑥ spec_from_html 往返无损（交付只剩一个 HTML 后，靠它把数据捞回来）
run_build(sp_ok, 'rt.html', '--force')
r = subprocess.run([PY, SPEC_FROM_HTML, 'rt.html', 'rt.json'], capture_output=True, cwd=D7)
ok('spec_from_html 退出码 0', r.returncode == 0, r.stderr.decode('utf-8', 'replace')[:140])
code, out = run_build('rt.json', 'rt2.html', '--force')
ok('反解出的 spec 能直接重新生成', code == 0, out[-160:])
ok('往返后 HTML 内嵌数据完全一致',
   data_of(os.path.join(D7, 'rt.html')) == data_of(os.path.join(D7, 'rt2.html')))

# ⑦ 单双周 / 多段周次也要能往返
sp_par = os.path.join(D7, 'spec_par.json')
with open(sp_par, 'w', encoding='utf-8') as f:
    json.dump({'courses': [{'day': '周一', 'block': '1-2', 'name': '高等数学', 'weeks': '8-16单'},
                           {'day': '周二', 'block': '1-2', 'name': '大学物理', 'weeks': '9-17、19-21'}]},
              f, ensure_ascii=False)
run_build(sp_par, 'par.html', '--force')
subprocess.run([PY, SPEC_FROM_HTML, 'par.html', 'par.json'], capture_output=True, cwd=D7)
run_build('par.json', 'par2.html', '--force')
ok('单双周 / 多段周次往返无损',
   data_of(os.path.join(D7, 'par.html')) == data_of(os.path.join(D7, 'par2.html')))

print()
print('=' * 72)
print('8. 视觉自检工具（可选：没有浏览器必须优雅跳过）')
print('=' * 72)

VV = os.path.join(SCRIPTS, 'verify_visual.py')
NO_BROWSER = os.path.join(OUT, 'no-such-browser.exe')

code_check = subprocess.run([PY, VV, out_html, '--browser', NO_BROWSER], capture_output=True, cwd=D7)
out = (code_check.stdout + code_check.stderr).decode('utf-8', 'replace')
ok('没有浏览器 → 退出码 0（绝不阻塞交付）', code_check.returncode == 0, out[-200:])
ok('没有浏览器 → 打印人工目测清单', '人工确认' in out and '导出图片' in out, out[-160:])
ok('没有浏览器 → 不抛异常', 'Traceback' not in out, out[-160:])

r = subprocess.run([PY, VV], capture_output=True, cwd=D7)
ok('缺参数 → 退出码 2 并给用法', r.returncode == 2, str(r.returncode))
r = subprocess.run([PY, VV, os.path.join(D7, 'nope.html')], capture_output=True, cwd=D7)
ok('文件不存在 → 退出码 2', r.returncode == 2, str(r.returncode))

dirty_before = set(os.listdir(D7))
r = subprocess.run([PY, VV, out_html], capture_output=True, cwd=D7)
out = (r.stdout + r.stderr).decode('utf-8', 'replace')
ok('真跑一遍 → 退出码 0/1（几何结论），不是崩溃', r.returncode in (0, 1), out[-200:])
ok('结果里要么有量测数据、要么明确说明跳过',
   ('视口' in out) or ('人工确认' in out), out[-200:])
ok('量测过程不往工作目录留任何文件（走临时目录）',
   set(os.listdir(D7)) == dirty_before, str(set(os.listdir(D7)) - dirty_before))

shotdir = os.path.join(OUT, 'shots')
r = subprocess.run([PY, VV, out_html, '--shot', shotdir], capture_output=True, cwd=D7)
out = (r.stdout + r.stderr).decode('utf-8', 'replace')
n_shots = len(glob.glob(os.path.join(shotdir, '*.png')))
if '视口' in out:
    ok('--shot 按场景出图（默认 2 档 → 2 张）', n_shots == 2, str(n_shots))
else:
    ok('--shot 无浏览器时不出图也不报错', n_shots == 0 and r.returncode == 0, '本机无浏览器，跳过')

print()
print('=' * 72)
print('9. 回归：以前会静默通过的错误，现在必须被拦住')
print('=' * 72)

D9 = os.path.join(OUT, 'regress')
os.makedirs(D9, exist_ok=True)


def build_spec(name, obj, *args):
    """写一个 spec 跑 build，返回 (returncode, 合并输出)"""
    p = os.path.join(D9, name)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False)
    r = subprocess.run([PY, BUILD, p] + list(args), capture_output=True, cwd=D9, env=SUBENV)
    return r.returncode, (r.stdout + r.stderr).decode('utf-8', 'replace')


ONE = [{'day': '周一', 'block': '1-2', 'name': 'A', 'weeks': '8-16'}]

# ① 周次跨度三个字段的交叉校验（以前 maxWeek 写小会静默吃掉后半学期的课，
#    而 build 摘要 / check / render 三套防线全部放行）
code, out = build_spec('mw.json', {'maxWeek': 10, 'courses': ONE}, '--detect')
ok('maxWeek 小于课程最晚周次 → 报错', code != 0 and '静默丢掉' in out, out[-150:])
code, out = build_spec('dw.json', {'defaultWeek': 99, 'courses': ONE}, '--detect')
ok('defaultWeek 越界 → 报错', code != 0 and '空表' in out, out[-150:])
code, out = build_spec('minw.json', {'minWeek': 12, 'courses': ONE}, '--detect')
ok('minWeek 晚于课程最早周次 → 报错', code != 0 and '静默丢掉' in out, out[-150:])
code, out = build_spec('span.json', {'minWeek': 8, 'maxWeek': 16, 'defaultWeek': 12, 'courses': ONE}, '--detect')
ok('合法的 minWeek/maxWeek/defaultWeek 仍然放行', code == 0, out[-150:])

# ② 各种坏输入必须说人话（以前是裸 traceback）
bom = os.path.join(D9, 'bom.json')
open(bom, 'wb').write('\ufeff'.encode('utf-8') + json.dumps({'courses': ONE}, ensure_ascii=False).encode('utf-8'))
r = subprocess.run([PY, BUILD, bom, '--detect'], capture_output=True, cwd=D9, env=SUBENV)
ok('带 BOM 的 spec（记事本默认）能直接读', r.returncode == 0, r.stderr.decode('utf-8', 'replace')[:120])

p = os.path.join(D9, 'broken.json')
open(p, 'w', encoding='utf-8').write('{ 这不是 JSON')
r = subprocess.run([PY, BUILD, p, '--detect'], capture_output=True, cwd=D9, env=SUBENV)
ok('坏 JSON → 可读报错、不是 traceback',
   b'Traceback' not in r.stderr and any(m in r.stderr for m in ERR_MARKS),
   r.stderr.decode('utf-8', 'replace')[:120])

code, out = build_spec('arr.json', [1, 2, 3], '--detect')
ok('顶层是数组 → 可读报错', code != 0 and 'Traceback' not in out, out[-120:])
code, out = build_spec('badcourses.json', {'courses': 'abc'}, '--detect')
ok('courses 是字符串 → 可读报错', code != 0 and 'Traceback' not in out, out[-120:])

# ③ 未知开关（以前会生成一个名为 --foo 的文件）
code, out = build_spec('flag.json', {'courses': ONE}, '--foo')
ok('未知开关 → 报错，不生成怪文件', code != 0 and '未知参数' in out, out[-120:])

# ④ 课程名含 </script> → 产物不得被截断
code, out = build_spec('xss.json', {'courses': [{'day': '周一', 'block': '1-2',
                                                 'name': 'X</script><b>Y', 'weeks': '1-16'}]},
                       'xss.html', '--force')
xss = open(os.path.join(D9, 'xss.html'), encoding='utf-8').read()
data_part = xss.split('const DATA = ', 1)[1].split('\n};', 1)[0]
ok('课程名含 </script> 时数据段不被提前闭合',
   code == 0 and '</script>' not in data_part and '\\u003c/script' in data_part,
   f"data 段里 </script> 出现 {data_part.count('</script>')} 次")

# ⑤ 单双周摘要不再多拼一个「周」
code, out = build_spec('par.json', {'courses': [{'day': '周一', 'block': '1-2',
                                                 'name': 'A', 'weeks': '8-16单'}]}, '--detect')
ok('摘要里单双周写成「第 8-16 单周」而不是「…单周 周」',
   '第 8-16 单周 |' in out and '单周 周' not in out, out[-200:])

# ⑥ check_timetable 必须能发现被篡改的 HTML（负向测试：以前它完全失效也全绿）
tamper_spec = os.path.join(D9, 'tamper.json')
with open(tamper_spec, 'w', encoding='utf-8') as f:
    json.dump({'defaultWeek': 1, 'courses': [{'day': '周一', 'block': '1-2',
                                              'name': 'A', 'weeks': '1-16'}]}, f, ensure_ascii=False)
subprocess.run([PY, BUILD, tamper_spec, os.path.join(D9, 't_good.html'), '--force'],
               capture_output=True, cwd=D9, env=SUBENV)
good = open(os.path.join(D9, 't_good.html'), encoding='utf-8').read()
ok('正常产物 → check 退出码 0',
   subprocess.run([PY, CHECK, tamper_spec, os.path.join(D9, 't_good.html')],
                  capture_output=True, cwd=D9, env=SUBENV).returncode == 0)
for label, old, new in (('defaultWeek', '"defaultWeek": 1', '"defaultWeek": 99'),
                        ('days', '"周一",\n  "周二",', '"周一",'),
                        ('blocks', '"1-2",\n  "3-4",', '"1-2",')):
    bad = os.path.join(D9, f't_bad_{label}.html')
    open(bad, 'w', encoding='utf-8').write(good.replace(old, new, 1))
    r = subprocess.run([PY, CHECK, tamper_spec, bad], capture_output=True, cwd=D9, env=SUBENV)
    ok(f'check 能发现被篡改的 {label}', r.returncode != 0, r.stdout.decode('utf-8', 'replace')[-160:])

# ⑦ spec_from_html 不覆盖既有 spec.json，并保留周次跨度三个字段
sentinel = os.path.join(D9, 'spec.json')
open(sentinel, 'w', encoding='utf-8').write('{"SENTINEL": true}')
r = subprocess.run([PY, SPEC_FROM_HTML, os.path.join(D9, 't_good.html')], capture_output=True, cwd=D9, env=SUBENV)
ok('反解默认输出不覆盖既有 spec.json',
   json.load(open(sentinel, encoding='utf-8')) == {'SENTINEL': True}, r.stdout.decode('utf-8', 'replace')[-160:])
ok('反解改名为 spec2.json', os.path.exists(os.path.join(D9, 'spec2.json')))

subprocess.run([PY, BUILD, os.path.join(D9, 'span.json'), os.path.join(D9, 'span.html'), '--force'],
               capture_output=True, cwd=D9, env=SUBENV)
subprocess.run([PY, SPEC_FROM_HTML, os.path.join(D9, 'span.html'), os.path.join(D9, 'span_back.json')],
               capture_output=True, cwd=D9, env=SUBENV)
subprocess.run([PY, BUILD, os.path.join(D9, 'span_back.json'), os.path.join(D9, 'span2.html'), '--force'],
               capture_output=True, cwd=D9, env=SUBENV)
ok('反解保留 minWeek/maxWeek/defaultWeek（往返后数据完全一致）',
   data_of(os.path.join(D9, 'span.html')) == data_of(os.path.join(D9, 'span2.html')))

# ⑧ check 的报告跨度必须与 build 一致（以前硬编码"第 1 ~ N 周"）
r = subprocess.run([PY, CHECK, os.path.join(D9, 'span.json'), os.path.join(D9, 'span.html')],
                   capture_output=True, cwd=D9, env=SUBENV)
out = r.stdout.decode('utf-8', 'replace')
ok('check 报告用真实跨度「第 8 ~ 16 周」且不打印第 1-7 周的空行',
   '第 8 ~ 16 周' in out and '第 1周' not in out, out[-200:])

# ⑨ 全字段往返：中间表示必须无损（每个字段都要能被反解回来）
FULL = {
    'who': '张三', 'term': '2026 秋',
    'days': ['周一', '周二', '周三', '周四', '周五'],
    'blocks': ['1-2', '3-4', '5-8', '9-10'],
    'hideEmptyDays': True,
    'minWeek': 6, 'maxWeek': 22, 'defaultWeek': 9,
    'courses': [
        {'day': '周一', 'block': '1-2', 'name': '高等数学', 'room': '教三-201', 'teacher': '李老师', 'weeks': '8-16'},
        {'day': '周三', 'block': '5-8', 'name': '大学物理', 'room': '', 'teacher': '', 'weeks': '9-14、19-21'},
        {'day': '周五', 'block': '9-10', 'name': '专业英语', 'weeks': '8-16双'},
    ],
}
code, out = build_spec('full.json', FULL, 'full.html', '--force')
ok('全字段 spec 能生成', code == 0, out[-160:])
subprocess.run([PY, SPEC_FROM_HTML, os.path.join(D9, 'full.html'), os.path.join(D9, 'full_back.json')],
               capture_output=True, cwd=D9, env=SUBENV)
back = json.load(open(os.path.join(D9, 'full_back.json'), encoding='utf-8'))
for k in ('who', 'term', 'days', 'blocks', 'hideEmptyDays', 'minWeek', 'maxWeek', 'defaultWeek'):
    ok(f'反解保留了 {k}', back.get(k) == FULL[k], f'spec={FULL[k]!r} 反解={back.get(k)!r}')
ok('反解保留了每条的 教室/教师/周次（含单双周与多段）',
   [(c['room'], c['teacher'], c['weeks']) for c in back['courses']] ==
   [('教三-201', '李老师', '8-16'), ('', '', '9-14、19-21'), ('', '', '8-16双')],
   str([(c['room'], c['teacher'], c['weeks']) for c in back['courses']]))
subprocess.run([PY, BUILD, os.path.join(D9, 'full_back.json'), os.path.join(D9, 'full2.html'), '--force'],
               capture_output=True, cwd=D9, env=SUBENV)
ok('全字段往返后 HTML 数据完全一致',
   data_of(os.path.join(D9, 'full.html')) == data_of(os.path.join(D9, 'full2.html')))

# ⑩ 未知键名必须报错 —— 拼错 classroom / teahcer / wko 曾被静默丢弃
code, out = build_spec('badkey.json', {'courses': [{'day': '周一', 'block': '1-2', 'name': 'A',
                                                    'weeks': '1-16', 'classroom': '教三-201'}]}, '--detect')
ok('课程里写错键名 → 报错并给出提示（不再静默丢字段）',
   code != 0 and 'classroom' in out and 'room' in out and 'Traceback' not in out, out[-220:])
code, out = build_spec('badkey2.json', {'wko': '张三', 'courses': ONE}, '--detect')
ok('顶层写错键名 → 报错', code != 0 and 'wko' in out and 'Traceback' not in out, out[-220:])
code, out = build_spec('okkey.json', {'_说明': '临时注释', '_note': 'x', 'title': '旧字段',
                                      'courses': [dict(ONE[0], _x=1)]}, '--detect')
ok('下划线注释键与已废弃的 title 仍然放行', code == 0, out[-220:])

# ⑪ days / blocks 的元素类型（以前 days 混进数字会在 "、".join 抛裸 traceback）
code, out = build_spec('daysbad.json', {'days': ['周一', 2], 'courses': ONE}, '--detect')
ok('days 混进数字 → 友好报错、不是 traceback',
   code != 0 and 'Traceback' not in out and '✗' in out, out[-220:])
code, out = build_spec('blocksbad.json', {'blocks': ['1-2', None], 'courses': ONE}, '--detect')
ok('blocks 混进 null → 友好报错', code != 0 and 'Traceback' not in out, out[-220:])

# ⑫ 给"自检自己的牙"加断言：把 weekStats 改坏，render_weeks.js 必须抓到。
#    这一条守的是历史上那个死断言 —— stat.includes(String(n)) 曾被两个数字互相掩护。
if node_ok:
    teeth = os.path.join(D9, 'teeth.json')
    with open(teeth, 'w', encoding='utf-8') as f:
        json.dump({'courses': [{'day': '周一', 'block': '1-2', 'name': 'A', 'weeks': '1-16'},
                               {'day': '周三', 'block': '3-4', 'name': 'C', 'weeks': '1-16'}]},
                  f, ensure_ascii=False)
    good = os.path.join(D9, 'teeth.html')
    rc, _ = build_spec('teeth.json', {'courses': [{'day': '周一', 'block': '1-2', 'name': 'A', 'weeks': '1-16'},
                                                  {'day': '周三', 'block': '3-4', 'name': 'C', 'weeks': '1-16'}]},
                       'teeth.html', '--force')
    ok('变异测试的前置：样本产物生成成功', rc == 0 and os.path.exists(good), f'rc={rc}')
    src = open(good, encoding='utf-8').read() if os.path.exists(good) else ''
    patched = src.replace('return { count:n, slots:slots };', 'return { count:n+1, slots:slots };')
    ok('变异补丁能打上（模板里 weekStats 的结构没变）',
       bool(src) and patched != src, '找不到 return { count:n, slots:slots };')
    broken = os.path.join(D9, 'teeth_broken.html')
    open(broken, 'w', encoding='utf-8').write(patched)
    r = subprocess.run([NODE, RENDER, broken], capture_output=True, cwd=D9, env=SUBENV)
    out = (r.stdout + r.stderr).decode('utf-8', 'replace')
    ok('统计行被改坏时 render_weeks.js 必须失败（这条断言以前是死的）',
       r.returncode != 0 and '统计行' in out, out[-220:])

print()
print('=' * 72)
print(f'结果: {passed} 通过 / {failed} 失败')
print('=' * 72)
shutil.rmtree(OUT, ignore_errors=True)   # 跑完清掉临时产物，避免被打包带走
sys.exit(1 if failed else 0)
