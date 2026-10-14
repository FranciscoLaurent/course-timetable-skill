#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
核对生成的课表网页：spec ↔ HTML 一致性、逐周展开、冲突、边界周、模板残留。

用法:
    python check_timetable.py spec.json 输出.html

退出码 0 = 全部通过；1 = 发现问题（详情打印在 stdout）。

注意：本脚本验证的是"spec 与 HTML 是否一致、按周展开是否正确"；
      「学期总览」的渲染断言在 render_weeks.js 里（它跑的是页面真实脚本）。
      "spec 是否忠实于用户原话"必须由核对者**独立重新解析用户原话**来判定，
      不能靠本脚本代劳 —— 否则只是自己证明自己。
"""
import sys, os, json, re

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True          # 别在 skill 目录里留下 __pycache__
from build_timetable import (parse_weeks, to_ranges, clean_who, span_text,  # noqa: E402
                             DEFAULT_DAYS, DEFAULT_BLOCKS, SpecError)

PROBLEMS = []
WARNINGS = []


def problem(msg):
    PROBLEMS.append(msg)


def warn(msg):
    WARNINGS.append(msg)


def extract_data(html):
    """从 HTML 里取出 `const DATA = {...};` 这个 JSON 对象。"""
    m = re.search(r'const\s+DATA\s*=\s*', html)
    if not m:
        raise SpecError('HTML 里找不到 const DATA')
    i = html.index('{', m.end())
    depth, j, instr, esc = 0, i, False, False
    while j < len(html):
        ch = html[j]
        if instr:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                instr = False
        else:
            if ch == '"':
                instr = True
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return json.loads(html[i:j + 1])
        j += 1
    raise SpecError('DATA 的 JSON 没有闭合')


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    spec_path, html_path = sys.argv[1], sys.argv[2]

    try:
        with open(spec_path, encoding='utf-8-sig') as f:
            spec = json.load(f)
    except FileNotFoundError:
        raise SpecError(f'找不到 spec 文件: {spec_path}')
    except json.JSONDecodeError as e:
        raise SpecError(f'{spec_path} 不是合法 JSON（第 {e.lineno} 行第 {e.colno} 列）: {e.msg}')
    if not isinstance(spec, dict) or not isinstance(spec.get('courses'), list):
        raise SpecError('spec 顶层必须是对象，且 spec.courses 必须是数组')
    try:
        with open(html_path, encoding='utf-8-sig') as f:
            html = f.read()
    except FileNotFoundError:
        raise SpecError(f'找不到 HTML 文件: {html_path}')

    print('=' * 78)
    print('1. 模板残留 / 结构自检')
    print('=' * 78)
    if '__DATA__' in html:          # 必须在解析 DATA 之前查，否则会先 KeyError
        print('✗ HTML 里仍有未替换的 __DATA__ 占位符 —— 这不是 build_timetable.py 的产物')
        raise SystemExit(1)

    data = extract_data(html)

    # 期望值取自 spec（**不能**从 HTML 里兜底取值，否则是自己证自己）
    days = spec.get('days') or DEFAULT_DAYS
    blocks = [str(b) for b in (spec.get('blocks') or DEFAULT_BLOCKS)]
    courses = spec['courses']

    for needle in ('id="weekSel"', 'id="tbody"', 'id="grid"', 'id="title"', 'id="prev"', 'id="next"'):
        if needle not in html:
            problem(f'HTML 缺少必需元素 {needle}')
    ids_needed = set(re.findall(r"getElementById\('([^']+)'\)", html))
    ids_defined = set(re.findall(r'\bid="([^"]+)"', html))
    missing = ids_needed - ids_defined
    if missing:
        problem(f'JS 引用了不存在的元素 id: {sorted(missing)}')
    print(f'  文件大小 {os.path.getsize(html_path)} 字节；引用的元素 id {len(ids_needed)} 个，'
          f'未定义 {len(missing)} 个；{"✓ 通过" if not PROBLEMS else "✗ 见下"}')

    print()
    print('=' * 78)
    print('2. spec ↔ HTML 数据一致性')
    print('=' * 78)
    print(f'  spec 课程 {len(courses)} 条 / HTML 内嵌 {len(data["courses"])} 条')
    if len(courses) != len(data['courses']):
        problem(f'课程条数不一致: spec={len(courses)} html={len(data["courses"])}')
    for i, raw in enumerate(courses):
        wset, wtext = parse_weeks(raw.get('weeks'), f'courses[{i}]')
        want = {
            'day': raw.get('day'), 'block': str(raw.get('block')),
            'name': (raw.get('name') or '').strip(), 'room': (raw.get('room') or '').strip(),
            'teacher': (raw.get('teacher') or '').strip(),
            'weeks': to_ranges(wset), 'weeksText': wtext,
            'weeksLabel': ('第 ' + wtext) if wtext.endswith('周') else ('第 ' + wtext + ' 周'),
        }
        got = data['courses'][i] if i < len(data['courses']) else None
        if got is None:
            problem(f'courses[{i}] 在 HTML 中缺失')
            continue
        for k, v in want.items():
            if got.get(k) != v:
                problem(f"courses[{i}] {raw.get('name')} 字段 {k} 不一致: spec={v!r} html={got.get(k)!r}")
    if not PROBLEMS:
        print('  ✓ 每条课程的 day/block/name/room/weeks/weeksText 全部一致')

    # 全局字段：以前只查了 minWeek/maxWeek，days/blocks 等全是死变量 —— 改坏了也照样"通过"
    if [str(d) for d in days] != [str(d) for d in data.get('days', [])]:
        problem(f'days 不一致: spec={days} html={data.get("days")}')
    if blocks != [str(b) for b in data.get('blocks', [])]:
        problem(f'blocks 不一致: spec={blocks} html={data.get("blocks")}')
    for k, want in (
        ('minWeek', spec.get('minWeek')),
        ('maxWeek', spec.get('maxWeek')),
        ('defaultWeek', spec.get('defaultWeek')),
        ('term', (spec.get('term') or '').strip()),
        ('hideEmptyDays', bool(spec.get('hideEmptyDays', False))),
    ):
        if want is None and k in ('minWeek', 'maxWeek', 'defaultWeek'):
            continue                      # spec 没写 = 由脚本自动推算，不做比较
        if data.get(k) != want:
            problem(f'{k} 不一致: spec={want!r} html={data.get(k)!r}')
    if not any('不一致' in p for p in PROBLEMS):
        print('  ✓ days/blocks/minWeek/maxWeek/defaultWeek/term/hideEmptyDays 全部一致')

    # 姓名：默认留空，标题就是"第N周课表"。spec 里写了就照抄，但不能带"级/班"这类尾巴。
    want_who = clean_who(spec.get('who'))
    got_who = data.get('who') or ''
    if got_who != want_who:
        problem(f'who 不一致: spec={want_who!r} html={got_who!r}')
    elif want_who:
        print(f'  大标题带姓名：{want_who}第N周课表 / {want_who}学期课表总览')
    else:
        print('  大标题不带姓名（who 留空 —— 默认如此）')

    # 页面上不该出现"XX级 / XX班"这类建制标识（只告警，不影响退出码：课程名里
    # 偶然出现"X级"是可能的，交给人判断）
    for pat in (r'\d+\s*级', r'\d+\s*班', r'[XxＸ]{1,4}\s*级', r'[XxＸ]{1,4}\s*班'):
        for m in re.finditer(pat, html):
            warn(f'页面里出现疑似建制标识「{m.group(0)}」，非本 skill 生成时应删掉')
            break

    print()
    print('=' * 78)
    print('3. 逐周展开 / 冲突 / 边界周')
    print('=' * 78)
    parsed = []
    for i, raw in enumerate(courses):
        wset, wtext = parse_weeks(raw.get('weeks'), f'courses[{i}]')
        parsed.append({'day': raw.get('day'), 'block': str(raw.get('block')),
                       'name': (raw.get('name') or '').strip(),
                       'room': (raw.get('room') or '').strip(),
                       'teacher': (raw.get('teacher') or '').strip(),
                       'weeks': wset, 'text': wtext})

    lo = data.get('minWeek') or min(min(p['weeks']) for p in parsed)
    hi = data.get('maxWeek') or max(max(p['weeks']) for p in parsed)

    total = 0
    for w in range(lo, hi + 1):
        hit = [p for p in parsed if w in p['weeks']]
        slots = {}
        for p in hit:
            slots.setdefault((p['day'], p['block']), []).append(p['name'])
        clashes = {k: v for k, v in slots.items() if len(v) > 1}
        total += len(hit)
        for k, v in clashes.items():
            problem(f'第 {w} 周 {k[0]} {k[1]} 同时有两门课: {v}')
        marks = []
        for p in hit:
            if w == min(p['weeks']):
                marks.append(f"{p['name']} 开始")
            if w == max(p['weeks']):
                marks.append(f"{p['name']} 结束")
        line = f"  第{w:>2}周: {len(hit):>2} 门次 / {len(slots)} 时段"
        if marks:
            line += '   ← ' + '，'.join(marks)
        print(line)
    print(f'\n  合计 {total} 门次（{span_text(lo, hi)}）')
    if not any(p for p in PROBLEMS if '同时有两门课' in p):
        print('  ✓ 无同一周同一时段两门课')

    print()
    print('=' * 78)
    if WARNINGS:
        print(f'⚠ {len(WARNINGS)} 条告警（不阻塞退出码）:')
        for w in WARNINGS:
            print('   -', w)
        print('=' * 78)
    if PROBLEMS:
        print(f'✗ 发现 {len(PROBLEMS)} 个问题:')
        for p in PROBLEMS:
            print('   -', p)
        print('=' * 78)
        return 1
    print('✓ 全部检查通过（模板残留 / spec↔HTML 一致性 / 逐周展开 / 冲突）')
    print('提醒：以上只证明"HTML 忠实于 spec"。spec 是否忠实于用户原话，'
          '必须另行独立比对用户原话。')
    print('=' * 78)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except SpecError as e:
        print(f'✗ {e}', file=sys.stderr)
        raise SystemExit(1)
