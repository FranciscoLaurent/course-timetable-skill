#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把生成好的课表 HTML 反解回 spec.json —— 交付约定是「只留一个 课表.html」，
所以 spec.json 交付前会被清掉；用户下次想改课表时，用本脚本把数据捞回来。

用法:
    python spec_from_html.py 课表.html [spec.json]

反解出来的 spec 与当初手写的那份**内容等价**（含 who/term/days/blocks/
hideEmptyDays/minWeek/maxWeek/defaultWeek/每条课程），之后照常走
「改 spec → `--detect` 探测冲突 → 重新生成」。

**默认不覆盖既有文件**：`spec.json` 已存在时会自动改名 `spec2.json`，
和 build_timetable.py 同一条规矩。

只依赖 Python 3 标准库。它复用 check_timetable.py 的 extract_data()，
因此对 HTML 的解析规则只有一份，不会出现两套实现互相打架。
"""
import sys, os, json, re

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True          # 别在 skill 目录里留下 __pycache__
from check_timetable import extract_data                    # noqa: E402
from build_timetable import unique_out_path, SpecError      # noqa: E402


def canonical_weeks(text):
    """把页面里的 `weeksText` 还原成 spec 里的**规范形态**：`8-16 双周` → `8-16双`。

    注意它**不是为了能解析** —— `parse_weeks` 自己会吞掉「第 / 周 / 空格」，
    `8-16 双周` 也能解析。它存在是为了**形态统一**：
    反解出来的 spec 应该和当初手写的那份长得一样（`references/input-parsing.md` §3
    只规定了这一种写法），用户才敢直接上手改。
    """
    return re.sub(r'\s+', '', text or '').replace('周', '')


def main():
    if len(sys.argv) not in (2, 3):
        print(__doc__)
        return 2
    html_path = sys.argv[1]
    out_arg = sys.argv[2] if len(sys.argv) == 3 else 'spec.json'

    try:
        with open(html_path, encoding='utf-8-sig') as f:
            data = extract_data(f.read())
    except FileNotFoundError:
        print(f'✗ 找不到 HTML 文件: {html_path}', file=sys.stderr)
        return 1

    spec = {}
    if (data.get('who') or '').strip():
        spec['who'] = data['who'].strip()
    if (data.get('term') or '').strip():
        spec['term'] = data['term'].strip()
    spec['days'] = data['days']
    spec['blocks'] = data['blocks']
    if data.get('hideEmptyDays'):
        spec['hideEmptyDays'] = True
    # 周次跨度三个字段也要还原，否则「反解 → 重新生成」会悄悄把跨度/默认周改掉
    for k in ('minWeek', 'maxWeek', 'defaultWeek'):
        if data.get(k):
            spec[k] = data[k]
    spec['courses'] = [{
        'day': c['day'],
        'block': c['block'],
        'name': c['name'],
        'room': c.get('room') or '',
        'teacher': c.get('teacher') or '',
        # 交回给 parse_weeks 之前先归一成规范形态（见 canonical_weeks 的说明）
        'weeks': canonical_weeks(c.get('weeksText')),
    } for c in data['courses']]

    # 与 build_timetable 同一条规矩：绝不覆盖既有文件
    out_path, bumped = unique_out_path(out_arg)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(spec, f, ensure_ascii=False, indent=1)
        f.write('\n')

    print(f'✓ 已从 {os.path.basename(html_path)} 反解出 {len(spec["courses"])} 条课程 → '
          f'{os.path.abspath(out_path)}')
    if bumped:
        print(f'  （{os.path.basename(bumped)} 已存在，为免覆盖自动改名；'
              f'确认那是本任务的中间产物才手动删掉它）')
    print(f'  星期列 : {"、".join(spec["days"])}')
    print(f'  节次行 : {"、".join(str(b) for b in spec["blocks"])}')
    print(f'  周次   : {spec["courses"][0]["weeks"]} … {spec["courses"][-1]["weeks"]}')
    print('  下一步 : 改这个 spec → python build_timetable.py spec.json --detect → 重新生成')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except SpecError as e:
        print(f'✗ {e}', file=sys.stderr)
        raise SystemExit(1)
