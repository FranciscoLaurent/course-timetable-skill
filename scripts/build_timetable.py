#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 spec.json 渲染成一张课表网页：支持「按周查看」与「学期总览」两种看法。

用法:
    python build_timetable.py spec.json --detect   # 只探测冲突，不写文件
                                                   #   退出码 0 = 可以开工；1 = 有冲突，先问用户
    python build_timetable.py spec.json            # 生成，自动起名 课表.html（重名自动让开）

选项:
    --detect          只做解析与冲突探测，不写任何文件
    --force           输出文件已存在时，覆盖它（默认不覆盖，自动改叫 课表2.html）
    --allow-conflict  明知有时段冲突仍要生成（用户确认"就是这么排的"时才用）

只依赖 Python 3 标准库。模板路径按脚本自身位置解析（../assets/timetable.template.html），
因此整个 skill 目录可以整体拷贝到任何地方使用。

**输出文件名**：不写第三个参数时自动用 `课表.html`；若该名字已被占用（比如目录里
已经有别人的课表），自动改用 `课表2.html`、`课表3.html`…，**绝不覆盖既有文件**。
选了哪个名字会打印在最后一行 `输出 : …`，后续自检 / 交付都用那个名字。

spec.json 格式:
{
  "who":        "张三",                  // 一般不要填。只有用户明确要求标题带姓名时才写；
                                        //   填了 = "<who>第N周课表"，不填 = "第N周课表"
  "term":       "2026 秋",              // 可选，显示在页脚（只写学期，不要写年级/班级）
  "days":       ["周一","周二","周三","周四","周五","周六","周日"],   // 可选，默认 7 天
  "blocks":     ["1-2","3-4","5-7","8-10"],                          // 可选，默认 4 段
  "hideEmptyDays": false,               // 可选，默认 false=一周 7 天都显示（周末默认有课）
                                        //   用户说"我们周末没课"时才写 true
  "defaultWeek": 8,                     // 可选，打开时默认显示第几周；默认=第一门课的起始周
  "minWeek": 8, "maxWeek": 22,          // 可选，覆盖自动推算的周次跨度
  "courses": [
    {"day":"周一","block":"1-2","name":"高等数学","room":"教三-201","teacher":"李老师",
     "weeks":"8-16","weaker":"",          // weeks 支持:
                                          //   "8-16"       连续区间
                                          //   "9-17、19-21" 多段（、,，;；/ 分隔）
                                          //   "8"          单周
                                          //   "8-16单"     区间内单周（奇数周）
                                          //   "8-16双"     区间内双周（偶数周）
     "note":""}                           // 可选备用字段
  ]
}
同一 (day, block) 可以写多门课：周次不重叠时正常轮换，重叠时会给出冲突警告。
"""
import sys, os, json, re

# 幂等设置 UTF-8 输出：不要用 io.TextIOWrapper 包装 sys.stdout，
# 否则本模块被其它脚本 import 时会二次包装，旧包装器回收时关闭底层缓冲。
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, os.pardir, 'assets', 'timetable.template.html')

DEFAULT_DAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
DEFAULT_BLOCKS = ['1-2', '3-4', '5-7', '8-10']
DEFAULT_OUT_NAME = '课表.html'
FULLWIDTH = str.maketrans('０１２３４５６７８９～－　）', '0123456789~- )')

# 允许出现的键。写错键名（classroom / teahcer / wko）如果只是被忽略，
# 字段就会**静默消失**、三道门禁全绿 —— 那正是这个 skill 最想避免的错。
# 下划线开头的键一律当注释放行（"_说明" / "_note" 这种写法）。
ALLOWED_TOP_KEYS = {'who', 'term', 'days', 'blocks', 'hideEmptyDays',
                    'defaultWeek', 'minWeek', 'maxWeek', 'courses', 'title'}
ALLOWED_COURSE_KEYS = {'day', 'block', 'name', 'room', 'teacher', 'weeks', 'note'}


def check_keys(obj, allowed, where):
    """拒绝不认识的键名，并给一个"是不是想写 X"的提示。"""
    bad = [k for k in obj if k not in allowed and not str(k).startswith('_')]
    if not bad:
        return
    hints = []
    for k in bad:
        hit = sorted([a for a in allowed if a in str(k)], key=len, reverse=True)
        hints.append(f'{k!r}' + (f'（是不是想写 {hit[0]!r}？）' if hit else ''))
    raise SpecError(f'{where} 有无法识别的字段：' + '，'.join(hints)
                    + f'；允许的字段是 {sorted(allowed)}'
                    + '（要写备注请用下划线开头，例如 "_说明"）')


class SpecError(Exception):
    pass


CN_DIGIT = {'零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
            '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
CN_RUN = re.compile(r'[零〇一二两三四五六七八九十]+')

# 姓名后面常见的建制尾巴：「（2026级）」「(2班)」
WHO_TAIL = re.compile(r'[（(][^）)]*(?:级|班)[^）)]*[）)]')


def clean_who(s):
    """姓名清洗。**默认留空**——不写就不显示，页面大标题就是"第N周课表"。

    用户明确要求标题带姓名时才写 who；这里顺手把"（2026级）/（2班）"这种
    建制尾巴去掉，免得它们出现在页面上（各校建制叫法不同，写了别人看不懂）。
    """
    s = WHO_TAIL.sub('', s or '')
    return re.sub(r'\s+', ' ', s).strip()


def cn2num(s):
    """中文数字 → 整数（支持 1~99，如 八、十六、二十一）。无法解析返回 None。"""
    if not s:
        return None
    if '十' not in s:
        return CN_DIGIT.get(s) if len(s) == 1 else None
    head, _, tail = s.partition('十')
    if head and head not in CN_DIGIT:
        return None
    if tail and tail not in CN_DIGIT:
        return None
    return (CN_DIGIT[head] if head else 1) * 10 + (CN_DIGIT[tail] if tail else 0)


def parse_weeks(raw, where):
    """把用户写法解析成 (周号集合, 规范化显示文本)。支持阿拉伯/中文数字、单双周。"""
    if raw is None or str(raw).strip() == '':
        raise SpecError(f'{where}: 缺少 weeks（周次）')
    s = str(raw).translate(FULLWIDTH).strip()
    s = s.replace('周', '').replace('第', '')
    s = s.replace('，', '、').replace(',', '、')
    s = s.replace('；', '、').replace(';', '、').replace('/', '、')
    s = re.sub(r'[~～—–－]', '-', s)
    s = s.replace('到', '-').replace('至', '-')
    # 中文数字 → 阿拉伯数字（"八到十六" → "8-16"）。注意 0 是合法结果，不能用真值判断。
    s = CN_RUN.sub(lambda m: (lambda n: m.group(0) if n is None else str(n))(cn2num(m.group(0))), s)
    s = re.sub(r'\s+', '', s)

    weeks, texts = set(), []
    for token in [t for t in s.split('、') if t]:
        parity = None
        for suffix, p in (('单', 'odd'), ('双', 'even')):
            if token.endswith(suffix):
                parity, token = p, token[:-len(suffix)]
                break
        m = re.fullmatch(r'(\d+)-(\d+)', token)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            label = f'{a}-{b}'
        else:
            m = re.fullmatch(r'(\d+)', token)
            if not m:
                raise SpecError(f'{where}: 无法解析周次 {token!r}（原始值 {raw!r}）')
            a = b = int(m.group(1))
            label = str(a)
        if a > b:
            raise SpecError(f'{where}: 周次区间起止颠倒 {token!r}')
        if a < 1 or b > 60:
            raise SpecError(f'{where}: 周次超出合理范围 {token!r}')
        rng = range(a, b + 1)
        if parity == 'odd':
            weeks |= {w for w in rng if w % 2 == 1}
            label += ' 单周'
        elif parity == 'even':
            weeks |= {w for w in rng if w % 2 == 0}
            label += ' 双周'
        else:
            weeks |= set(rng)
        texts.append(label)
    if not weeks:
        raise SpecError(f'{where}: 周次解析结果为空（原始值 {raw!r}）')
    return weeks, '、'.join(texts)


def to_ranges(weeks):
    """把周号集合压成连续区间列表 [[起,止], …]，供页面 JS 使用。"""
    out = []
    for w in sorted(weeks):
        if out and w == out[-1][1] + 1:
            out[-1][1] = w
        else:
            out.append([w, w])
    return out


def span_text(lo, hi):
    """周次跨度文案：单周时不要写成「第 8 ~ 8 周」。"""
    return f'第 {lo} 周' if lo == hi else f'第 {lo} ~ {hi} 周'


def unique_out_path(path):
    """不覆盖既有文件：path 被占用时改用 path2 / path3 …

    返回 (实际使用的路径, 被让开的原名或 None)。
    """
    if not os.path.exists(path):
        return path, None
    root, ext = os.path.splitext(path)
    for i in range(2, 1000):
        cand = f'{root}{i}{ext}'
        if not os.path.exists(cand):
            return cand, path
    raise SpecError(f'{path} 以及 2~999 号备选名全被占用，请手动指定输出文件名')


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    known = ('--detect', '--force', '--allow-conflict')
    unknown = [a for a in argv if a.startswith('--') and a not in known]
    if unknown:                      # 否则 --detectt 这类笔误会变成一个名为 --detectt 的输出文件
        raise SpecError(f'未知参数 {unknown}；只认 {", ".join(known)}')
    detect = '--detect' in argv
    force = '--force' in argv
    allow_conflict = '--allow-conflict' in argv
    argv = [a for a in argv if a not in known]
    if not 1 <= len(argv) <= 2:
        print(__doc__)
        return 2
    spec_path = argv[0]
    out_arg = argv[1] if len(argv) == 2 else os.path.join(os.getcwd(), DEFAULT_OUT_NAME)
    if os.path.isdir(out_arg):
        raise SpecError(f'输出路径是个目录: {out_arg} —— 请给具体文件名，'
                        f'例如 {os.path.join(out_arg, DEFAULT_OUT_NAME)}')

    # ── 读 spec：这是整条链路上唯一由人或 AI 手写的文件，错误必须说人话 ──
    try:
        with open(spec_path, encoding='utf-8-sig') as f:   # utf-8-sig：Windows 记事本存的 BOM 也认
            spec = json.load(f)
    except FileNotFoundError:
        raise SpecError(f'找不到 spec 文件: {spec_path}')
    except IsADirectoryError:
        raise SpecError(f'spec 路径是个目录: {spec_path}')
    except json.JSONDecodeError as e:
        raise SpecError(f'{spec_path} 不是合法 JSON（第 {e.lineno} 行第 {e.colno} 列）: {e.msg}')
    if not isinstance(spec, dict):
        raise SpecError(f'spec 顶层必须是对象 {{...}}，实得 {type(spec).__name__}')
    if not isinstance(spec.get('courses'), list) or not spec['courses']:
        raise SpecError('spec.courses 为空，没有可排的课程')
    for i, raw in enumerate(spec['courses']):
        if not isinstance(raw, dict):
            raise SpecError(f'courses[{i}] 必须是对象，实得 {type(raw).__name__}')
    check_keys(spec, ALLOWED_TOP_KEYS, 'spec')
    for i, raw in enumerate(spec['courses']):
        check_keys(raw, ALLOWED_COURSE_KEYS, f'courses[{i}]')

    # 只有"没写这个字段"才用默认值；显式写空数组是错误，不该被静默替换。
    # 元素类型也要查：days 里混进一个数字，曾经会在 "、".join(days) 处抛裸 TypeError。
    days = DEFAULT_DAYS if spec.get('days') is None else spec['days']
    blocks = DEFAULT_BLOCKS if spec.get('blocks') is None else spec['blocks']
    if not isinstance(days, list) or not days or not all(isinstance(d, str) for d in days):
        raise SpecError('days 必须是非空字符串数组（例如 ["周一","周二"]）；整个不写才用默认 7 天')
    if not isinstance(blocks, list) or not blocks or not all(isinstance(b, (str, int)) for b in blocks):
        raise SpecError('blocks 必须是非空数组、元素是字符串或整数（例如 ["1-2","3-4"]）；整个不写才用默认四段')

    courses, all_weeks, problems = [], set(), []
    for i, raw in enumerate(spec['courses']):
        where = f'courses[{i}]'
        day, block = raw.get('day'), raw.get('block')
        name = (raw.get('name') or '').strip()
        if not name:
            raise SpecError(f'{where}: 缺少 name（课程名）')
        if day not in days:
            raise SpecError(f'{where}: day={day!r} 不在 days={days} 中')
        if str(block) not in [str(b) for b in blocks]:
            raise SpecError(f'{where}: block={block!r} 不在 blocks={blocks} 中')
        wset, wtext = parse_weeks(raw.get('weeks'), where)
        # 显示文本在这里一次性拼好。注意单双周时 wtext 已以「周」结尾（如 "8-16 单周"），
        # 不能再补一个「周」，否则会出现「第 8-16 单周 周」。
        weeks_label = ('第 ' + wtext) if wtext.endswith('周') else ('第 ' + wtext + ' 周')
        all_weeks |= wset
        courses.append({
            'day': day,
            'block': str(block),
            'name': name,
            'room': (raw.get('room') or '').strip(),
            'teacher': (raw.get('teacher') or '').strip(),   # 可选：授课老师
            'weeks': to_ranges(wset),
            'weeksText': wtext,
            'weeksLabel': weeks_label,
        })
        courses[-1]['_weekset'] = wset

    # 冲突检查：同一天同一节次，周次有交集
    by_slot = {}
    for c in courses:
        by_slot.setdefault((c['day'], c['block']), []).append(c)
    for (day, block), items in by_slot.items():
        for x in range(len(items)):
            for y in range(x + 1, len(items)):
                overlap = items[x]['_weekset'] & items[y]['_weekset']
                if overlap:
                    problems.append(
                        f"{day} {block}：「{items[x]['name']}」与「{items[y]['name']}」"
                        f"在第 {min(overlap)}-{max(overlap)} 周有重叠")

    # ── 周次跨度必须与课程实际周次交叉校验 ──
    # 页面只渲染 1..maxWeek，所以 maxWeek 写小了会把后半学期的课**静默吃掉**；
    # defaultWeek 越界则打开就是一张空表。这两种错以前的三个校验器都发现不了。
    lo_auto, hi_auto = min(all_weeks), max(all_weeks)
    try:
        min_week = int(spec['minWeek']) if spec.get('minWeek') is not None else lo_auto
        max_week = int(spec['maxWeek']) if spec.get('maxWeek') is not None else hi_auto
    except (TypeError, ValueError):
        raise SpecError('minWeek / maxWeek 必须是整数（可以写 8 或 "8"）')
    if min_week > max_week:
        raise SpecError(f'minWeek({min_week}) 大于 maxWeek({max_week})')
    if max_week < hi_auto:
        raise SpecError(
            f'maxWeek({max_week}) 小于课程实际最晚的第 {hi_auto} 周 —— '
            f'第 {max_week + 1}-{hi_auto} 周会被静默丢掉；删掉 maxWeek 或改成 {hi_auto}')
    if min_week > lo_auto:
        raise SpecError(
            f'minWeek({min_week}) 晚于课程实际最早的第 {lo_auto} 周 —— '
            f'第 {lo_auto}-{min_week - 1} 周会被静默丢掉；删掉 minWeek 或改成 {lo_auto}')
    default_week = int(spec['defaultWeek']) if spec.get('defaultWeek') is not None else min_week
    if not min_week <= default_week <= max_week:
        raise SpecError(
            f'defaultWeek({default_week}) 不在第 {min_week}-{max_week} 周范围内，'
            f'页面打开会是一张空表；改成 {min_week}~{max_week} 之间的周次')

    for c in courses:
        c.pop('_weekset', None)

    data = {
        # 刻意不设 title：页面上不放"XX级/XX班"这类建制标识（各校叫法不同）。
        # 若 spec 里带了 title，这里直接忽略，避免它出现在产物里。
        # who 默认留空：用户没说名字 / 没要求写名字时，标题就是"第N周课表"。
        'who': clean_who(spec.get('who')),
        'term': (spec.get('term') or '').strip(),
        'days': days,
        'blocks': [str(b) for b in blocks],
        # 默认关闭：一周 7 天都显示，周末默认是"有课"的。
        # 只有用户明确说"我们周末没课"时才写 true（整周没课的天不显示列）。
        'hideEmptyDays': bool(spec.get('hideEmptyDays', False)),
        'minWeek': min_week,
        'maxWeek': max_week,
        'defaultWeek': default_week,
        # 刻意不放 generated（生成时间）：页面上不需要暴露这个
        'courses': courses,
    }

    with open(TEMPLATE, encoding='utf-8') as f:
        tpl = f.read()
    if '__DATA__' not in tpl:
        raise SpecError(f'模板缺少 __DATA__ 占位符: {TEMPLATE}')
    # `<` 写成 \u003c：JSON 里等价，但能挡住课程名里的 `</script>` 提前闭合页面脚本
    payload = json.dumps(data, ensure_ascii=False, indent=1).replace('<', '\\u003c')
    html = tpl.replace('__DATA__', payload)

    # ── 摘要 ──
    print(f'模板     : {os.path.normpath(TEMPLATE)}')
    if data['who']:
        print(f'大标题   : {data["who"]}第N周课表 / {data["who"]}学期课表总览')
    else:
        print('大标题   : 第N周课表 / 学期课表总览（不带姓名，默认如此）')
    print(f'课程条目 : {len(courses)} 条，覆盖 {len(by_slot)} 个时段')
    print(f'周次跨度 : {span_text(min_week, max_week)}（默认打开第 {data["defaultWeek"]} 周）')
    print(f'星期列   : {"、".join(days)}')
    print(f'节次行   : {"、".join(str(b) for b in blocks)}')
    print()
    print('已排课程:')
    blk_order = [str(b) for b in blocks]
    for c in sorted(courses, key=lambda x: (days.index(x['day']), blk_order.index(x['block']))):
        room = c['room'] or '（未填教室）'
        # 用 weeksLabel（已经处理好"第 8-16 单周"这种结尾），不要再拼一次「周」
        print(f"  {c['day']} {c['block']:>4} | {c['name']} | {c['weeksLabel']} | {room}")
    print()

    # ── 冲突探测：本脚本同时充当"冲突检测器" ──
    # 有冲突就拒绝生成（退出码 1），避免做出一个"看起来正常其实排不下"的课表。
    if problems:
        print(f'⚠ 发现 {len(problems)} 处时段冲突:')
        for p in problems:
            print('   -', p)
        if not allow_conflict:
            print()
            print('✗ 有冲突：先回去问用户这几门课怎么处理，改完 spec 再跑一次。')
            print('  （用户确认"就是这么排的"时，加 --allow-conflict 才继续生成。）')
            print('  本次没有生成任何文件。')
            return 1
        print('  ⚠ 已按 --allow-conflict 继续（同一格的多门课会在页面上叠放显示）。')
    else:
        print('✓ 无时段冲突')

    if detect:
        print()
        print('（--detect：只做解析与冲突探测，没有写任何文件）')
        return 0

    # ── 起名：绝不覆盖既有文件 ──
    out_path, bumped = (out_arg, None) if force else unique_out_path(out_arg)

    d = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(d, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print()
    print(f'输出     : {os.path.abspath(out_path)}  ({os.path.getsize(out_path)} 字节)  ← 交付这个文件')
    if bumped:
        print(f'           （{os.path.basename(bumped)} 已被占用，自动让开；'
              f'确认那是本任务上一版的产物，才加 --force 覆盖它）')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except SpecError as e:
        print(f'✗ spec 有误: {e}', file=sys.stderr)
        raise SystemExit(1)
