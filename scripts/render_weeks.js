#!/usr/bin/env node
/**
 * 用真实渲染逻辑核对生成的课表网页。
 *
 * 用法:
 *   node render_weeks.js <课表.html>              # 打印每一周的课表（电脑版表格）
 *   node render_weeks.js <课表.html> 8 16 22      # 只打印指定周
 *   node render_weeks.js <课表.html> --mobile     # 打印手机版卡片布局
 *   node render_weeks.js <课表.html> --json       # 以 JSON 输出，便于程序比对
 *
 * 环境变量:
 *   VIEW_WIDTH=400   模拟手机宽度（<780 时默认走手机版）
 *   VIEW_SEARCH='?view=mobile'   模拟带参数的打开方式
 *
 * 做法：把 HTML 里的 <script> 原样抽出来，在最小 DOM 桩里执行
 *      （页面自己的 renderWeek 真跑一遍），再解析渲染出的 DOM 字符串。
 *      因此这里得到的是"页面实际会显示什么"，不是另写一套渲染。
 */
'use strict';
const fs = require('fs');
const path = require('path');

const file = process.argv[2];
if (!file) {
  console.error('用法: node render_weeks.js <课表.html> [周次…] [--json]');
  process.exit(2);
}
const argv = process.argv.slice(3);
const asJson = argv.includes('--json');
const asMobile = argv.includes('--mobile');
const wantWeeks = argv.filter(a => /^\d+$/.test(a)).map(Number);

const html = fs.readFileSync(file, 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.error('✗ HTML 里找不到 <script>'); process.exit(1); }

/* ---------- 最小 DOM 桩 ---------- */
const nodes = {};
function mkSelect() {
  const opts = []; let explicit = null;
  return {
    children: opts, hidden: false, disabled: false, textContent: '', innerHTML: '', value: '',
    set value(v) { explicit = String(v); },
    get value() { return explicit !== null ? explicit : (opts[0] ? opts[0].value : ''); },
    get selectedText() { const o = opts.find(o => o.value === this.value); return o ? o.textContent : '(无)'; },
    appendChild(c) { opts.push(c); },
    addEventListener() {}
  };
}
function mkEl(id) {
  return {
    id, textContent: '', innerHTML: '', hidden: false, value: '', disabled: false,
    children: [], attrs: {},
    addEventListener() {}, appendChild() {},
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return this.attrs[k]; }
  };
}
const getEl = (id) => nodes[id] || (nodes[id] = (id === 'weekSel' ? mkSelect() : mkEl(id)));

global.document = {
  title: '',
  body: { className: '' },
  getElementById: getEl,
  createElement: () => ({ value: '', textContent: '' }),
  addEventListener() {}
};
global.window = { innerWidth: Number(process.env.VIEW_WIDTH || 1200), addEventListener() {} };
global.location = { search: process.env.VIEW_SEARCH || '' };
global.history = { replaceState() {} };

let mod;
try {
  mod = eval(m[1] + '\n;({DATA:DATA,renderWeek:renderWeek,renderScope:renderScope,weekStats:weekStats,'
              + 'buildWeekMap:buildWeekMap,weekTitle:weekTitle,resolveView:resolveView,applyView:applyView,'
              + 'chooseView:chooseView,chooseScope:chooseScope,resolveScope:resolveScope,overviewTitle:overviewTitle,'
              + 'visibleDays:visibleDays,buildTableSVG:buildTableSVG,buildCardsSVG:buildCardsSVG,'
              + 'wrapLines:wrapLines,courseMetaText:courseMetaText,isWeekend:isWeekend,setPrintPage:setPrintPage})');
} catch (e) {
  // 页面脚本跑不起来（多半是产物被破坏，例如课程名里混进 </script>）
  console.error('✗ 页面脚本无法执行：' + e.message);
  console.error('  产物多半已损坏（检查课程名/教室里有没有 </script> 或奇怪的 HTML）');
  process.exit(1);
}
const DATA = mod.DATA;

/* 实际会显示哪些列：hideEmptyDays 打开时，整周都没课的那天不显示。
   这里独立重算一遍（不复用页面里的 visibleDays），两边若不一致就能被发现。 */
const usedDays = (function () {
  if (!DATA.hideEmptyDays) return DATA.days;
  const used = new Set(DATA.courses.map(c => c.day));
  const keep = DATA.days.filter(d => used.has(d));
  return keep.length ? keep : DATA.days;
})();

/* ---------- 解析渲染结果 ---------- */
function unesc(s) {
  return String(s).replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&amp;/g, '&');
}
/** 解析手机版卡片列表：#mlist 里每天一个 <section class="mday"> */
function parseMobile(html) {
  const out = [];
  for (const seg of html.split('<section class="mday').slice(1)) {
    out.push({
      day: unesc((seg.match(/<h3>([^<]*)/) || [, ''])[1]).trim(),
      cls: (seg.match(/^([^"]*)"/) || [, ''])[1].trim(),
      empty: /class="mempty"/.test(seg),
      pers: [...seg.matchAll(/class="mper">([^<]*)</g)].map(x => unesc(x[1]).trim()),
      names: [...seg.matchAll(/class="mname"[^>]*>([^<]*)</g)].map(x => unesc(x[1]).trim()),
      metas: [...seg.matchAll(/class="mmeta">([\s\S]*?)<\/div>/g)]
                .map(x => unesc(x[1].replace(/<[^>]*>/g, '')).trim())
    });
  }
  return out;
}
function parseRow(rowHtml) {
  const blk = (rowHtml.match(/<th scope="row">([\s\S]*?)<\/th>/) || [, ''])[1];
  const cells = [...rowHtml.matchAll(/<td([^>]*)>([\s\S]*?)<\/td>/g)];
  return {
    block: unesc(blk).trim(),
    cells: cells.map(cm => {
      const inner = cm[2];
      const courses = [...inner.matchAll(/<div class="course"[^>]*>([\s\S]*?)(?=<div class="course"|$)/g)].map(x => {
        const seg = x[1];
        const name = unesc((seg.match(/class="cname"[^>]*>([\s\S]*?)<\/div>/) || [, ''])[1]).trim();
        // 教室 / 教师 现在拼在同一行（"教室 X · 教师 Y"），整行取出后再拆
        const meta = unesc((seg.match(/class="croom"[^>]*>([\s\S]*?)<\/div>/) || [, ''])[1])
                       .replace(/<[^>]*>/g, '').trim();
        const room = (meta.match(/教室\s*([^·]*)/) || [, ''])[1].trim();
        const teacher = (meta.match(/教师\s*([^·]*)/) || [, ''])[1].trim();
        const weeks = unesc((seg.match(/class="cweeks"[^>]*>([\s\S]*?)<\/div>/) || [, ''])[1]).trim();
        return { name, room, teacher, weeks };
      });
      return courses;
    })
  };
}

function renderWeek(w) {
  mod.renderWeek(w);
  const tbody = getEl('tbody').innerHTML;
  const rows = tbody ? tbody.split('</tr>').filter(r => r.includes('<tr')).map(r => parseRow(r + '</tr>')) : [];
  return {
    week: w,
    title: getEl('title').textContent,
    stat: getEl('stat').textContent,
    gridHidden: !!getEl('grid').hidden,
    emptyBox: !!getEl('none').hidden ? '' : unesc(getEl('none').innerHTML),
    selectText: getEl('weekSel').selectedText,
    prevDisabled: !!getEl('prev').disabled,
    nextDisabled: !!getEl('next').disabled,
    /* 手机内导航：必须在渲染当时快照，不能事后读实时 DOM（那时已是最后一次渲染的状态） */
    pWeek: getEl('pWeek').value,
    pTitle: getEl('pTitle').textContent,
    pPrevDisabled: !!getEl('pPrev').disabled,
    pNextDisabled: !!getEl('pNext').disabled,
    mobileEmpty: /class="pEmpty"/.test(getEl('mlist').innerHTML),
    rows,
    mobile: parseMobile(getEl('mlist').innerHTML)
  };
}

/* ---------- 断言 ---------- */
const failures = [];
function assert(name, cond, detail) { if (!cond) failures.push(name + (detail ? '  ← 实测: ' + detail : '')); }

const maxW = DATA.maxWeek;
const weeks = wantWeeks.length ? wantWeeks : Array.from({ length: maxW }, (_, i) => i + 1);
const results = weeks.map(renderWeek);

for (const r of results) {
  if (!r.gridHidden) {
    const n = r.rows.reduce((a, row) => a + row.cells.reduce((b, cs) => b + cs.length, 0), 0);
    // 注意：不能用 stat.includes(String(n)) —— 统计行是「本周共 N 门次课，占用 M 个时段」，
    // 里面有两个数字互相掩护（"共 12 门次" 里的 "2" 会让 n=2 通过），门次==时段时更是恒真。
    // 必须把门次数读出来精确比较。
    const mStat = /共\s*(\d+)\s*门次课/.exec(r.stat);
    if (!mStat) {
      failures.push(`第 ${r.week} 周：统计行里读不出门次数（"${r.stat}"）`);
    } else if (Number(mStat[1]) !== n) {
      failures.push(`第 ${r.week} 周：统计行说 ${mStat[1]} 门次，实际画出 ${n} 张卡片`);
    }
    if (r.rows.length !== DATA.blocks.length) failures.push(`第 ${r.week} 周：行数 ${r.rows.length} ≠ 节次段数 ${DATA.blocks.length}`);
    r.rows.forEach((row, i) => {
      if (row.cells.length !== usedDays.length) failures.push(`第 ${r.week} 周第 ${i + 1} 行：列数 ${row.cells.length} ≠ 应显示天数 ${usedDays.length}`);
    });
  } else if (!r.stat.includes('没有')) {
    failures.push(`第 ${r.week} 周：表格隐藏但统计行未提示无课`);
  }
  // 选周控件必须与页面同步（空周也不例外）
  if (r.selectText !== `第 ${r.week} 周` && !r.selectText.startsWith(`第 ${r.week} 周`)) {
    failures.push(`第 ${r.week} 周：下拉框显示 "${r.selectText}"，与页面不同步`);
  }
  if (r.title !== (DATA.who || '') + '第' + r.week + '周课表') {
    failures.push(`第 ${r.week} 周：大标题 "${r.title}" 不符`);
  }
  if (r.prevDisabled !== (r.week <= 1)) failures.push(`第 ${r.week} 周："上一周"按钮 disabled=${r.prevDisabled}`);
  if (r.nextDisabled !== (r.week >= maxW)) failures.push(`第 ${r.week} 周："下一周"按钮 disabled=${r.nextDisabled}`);

  /* ---- 手机版里的导航必须与页面同步 ---- */
  if (r.pWeek !== String(r.week)) {
    failures.push(`第 ${r.week} 周：手机内周次下拉显示 "${r.pWeek}"，未同步`);
  }
  if (r.pTitle !== r.title) {
    failures.push(`第 ${r.week} 周：手机内标题 "${r.pTitle}" ≠ "${r.title}"`);
  }
  if (r.pPrevDisabled !== r.prevDisabled) failures.push(`第 ${r.week} 周：手机内"上一周"置灰状态不一致`);
  if (r.pNextDisabled !== r.nextDisabled) failures.push(`第 ${r.week} 周：手机内"下一周"置灰状态不一致`);

  /* ---- 手机版必须与电脑版显示同样的内容 ---- */
  const days = usedDays;
  if (r.gridHidden) {
    if (r.mobile.length) failures.push(`第 ${r.week} 周：无课但手机版仍有 ${r.mobile.length} 张卡片`);
    if (!r.mobileEmpty) failures.push(`第 ${r.week} 周：手机内没有显示"没有课"的空状态`);
  } else {
    if (r.mobileEmpty) failures.push(`第 ${r.week} 周：有课却显示了空状态`);
    if (r.mobile.length !== days.length) {
      failures.push(`第 ${r.week} 周：手机版 ${r.mobile.length} 张卡片 ≠ 天数 ${days.length}`);
    } else {
      r.mobile.forEach((m, di) => {
        if (m.day !== days[di]) failures.push(`第 ${r.week} 周：手机版第 ${di + 1} 张卡片是「${m.day}」，应为「${days[di]}」`);
        // 电脑版该天的课程（跨所有节次块）
        const webNames = [];
        r.rows.forEach(row => (row.cells[di] || []).forEach(c => webNames.push(c.name)));
        const same = webNames.slice().sort().join('|') === m.names.slice().sort().join('|');
        if (!same) failures.push(`第 ${r.week} 周 ${m.day}：电脑版 [${webNames}] ≠ 手机版 [${m.names}]`);
        // 教室 / 教师 也必须一致
        const webRooms = [];
        r.rows.forEach(row => (row.cells[di] || []).forEach(c => webRooms.push(c.room)));
        const mobRooms = m.metas.map(t => (t.match(/教室\s*([^·]*)/) || [, ''])[1].trim());
        if (webRooms.slice().sort().join('|') !== mobRooms.slice().sort().join('|')) {
          failures.push(`第 ${r.week} 周 ${m.day}：电脑版教室 [${webRooms}] ≠ 手机版教室 [${mobRooms}]`);
        }
        if (m.pers.length !== m.names.length) failures.push(`第 ${r.week} 周 ${m.day}：手机版节次标签数 ≠ 课程数`);
        if (!m.names.length && !m.empty) failures.push(`第 ${r.week} 周 ${m.day}：手机版无课但未显示 empty 提示`);
        if (m.names.length && m.empty) failures.push(`第 ${r.week} 周 ${m.day}：手机版有课却显示 empty 提示`);
        // 节次标签必须按 blocks 顺序递增
        m.pers.forEach(p => {
          if (DATA.blocks.indexOf(p) < 0) failures.push(`第 ${r.week} 周 ${m.day}：手机版节次标签「${p}」不在 blocks 中`);
        });
      });
    }
  }
}
// 同一周同一时段不得出现两门课
for (const r of results) {
  if (r.gridHidden) continue;
  r.rows.forEach(row => row.cells.forEach((cs, di) => {
    if (cs.length > 1) failures.push(`第 ${r.week} 周 ${usedDays[di]} ${row.block}：同时有 ${cs.length} 门课`);
  }));
}

/* ---- 视图切换（电脑版 / 手机版） ---- */
const initialView = mod.resolveView();
(function () {
  const v0 = initialView;
  if (v0 !== 'web' && v0 !== 'mobile') failures.push(`resolveView() 返回非法值 ${v0}`);
  mod.chooseView('mobile');
  if (document.body.className !== 'view-mobile') failures.push(`切到手机版后 body.className="${document.body.className}"`);
  if (getEl('viewMobile').getAttribute('aria-pressed') !== 'true') failures.push('手机版按钮未标记为选中');
  if (getEl('viewWeb').getAttribute('aria-pressed') !== 'false') failures.push('电脑版按钮不应选中');
  mod.chooseView('web');
  if (document.body.className !== 'view-web') failures.push(`切回电脑版后 body.className="${document.body.className}"`);
  if (getEl('viewWeb').getAttribute('aria-pressed') !== 'true') failures.push('电脑版按钮未标记为选中');
  mod.chooseView('mobile');   // 留在手机版，便于 --mobile 输出
})();

/* ---- 导出图片用的 SVG（"导出图片"按钮走的就是这两个函数） ---- */
const svgWeek = wantWeeks.length ? wantWeeks[0]
               : (function () { for (let w = 1; w <= maxW; w++) if (mod.weekStats(mod.buildWeekMap()[w] || {}).count) return w; return 1; })();
const svgMap = mod.buildWeekMap()[svgWeek] || {};
const svgDays = mod.visibleDays();
const svgTitle = mod.weekTitle(svgWeek);
const svgTable = mod.buildTableSVG(svgTitle, svgMap, svgDays);
const svgCards = mod.buildCardsSVG(svgTitle, svgMap, svgDays);

function checkSvg(name, s) {
  if (!/^<svg [^>]*width="\d+" height="\d+"/.test(s)) failures.push(`${name}：开头不是合法的 <svg width height>`);
  if (!/<\/svg>$/.test(s)) failures.push(`${name}：结尾不是 </svg>`);
  if (/&(?!(amp|lt|gt|quot|apos|#\d+);)/.test(s)) failures.push(`${name}：含未转义的 &（XML 会解析失败）`);
  const open = (s.match(/<text\b/g) || []).length, close = (s.match(/<\/text>/g) || []).length;
  if (open !== close) failures.push(`${name}：<text> ${open} 个 ≠ </text> ${close} 个`);
  if (/undefined|NaN/.test(s)) failures.push(`${name}：含 undefined / NaN`);
  const tags = s.match(/<(\w+)[\s>]/g) || [];
  tags.forEach(t => {
    const n = t.replace(/[<\s>]/g, '');
    if (['svg', 'text', 'rect', 'line', 'path'].indexOf(n) < 0) failures.push(`${name}：出现了预期外的标签 <${n}>`);
  });
}
checkSvg('表格 SVG（电脑版导出）', svgTable);
checkSvg('卡片 SVG（手机版导出）', svgCards);

/* ---- 打印纸张：手机版必须和手机版图片同尺寸，不能是 A4 横版 ---- */
(function () {
  const el = getEl('pageStyle');
  const sm = /<svg[^>]*\bwidth="(\d+)"[^>]*\bheight="(\d+)"/.exec(svgCards);
  const cw = +sm[1], ch = +sm[2];
  mod.renderWeek(svgWeek);          // 必须先渲染到同一周，否则比的是两个不同周的尺寸

  mod.chooseView('web');
  mod.setPrintPage();
  if (!/size:\s*A4 landscape/.test(el.textContent)) {
    failures.push(`电脑版纸张应为 A4 横向，实得「${el.textContent}」`);
  }

  mod.chooseView('mobile');
  mod.setPrintPage();
  const m = /size:\s*([\d.]+)mm\s+([\d.]+)mm/.exec(el.textContent);
  if (!m) {
    failures.push(`手机版纸张没设成自定义尺寸，实得「${el.textContent}」`);
  } else {
    const wpx = Math.round(parseFloat(m[1]) * 96 / 25.4);
    const hpx = Math.round(parseFloat(m[2]) * 96 / 25.4);
    if (wpx !== cw) {
      failures.push(`手机版纸张宽 ${wpx}px 与手机版图片宽 ${cw}px 不一致`);
    }
    // 高度允许比图片多出一点点（刻意留的 1mm 余量，防止四舍五入挤出第二页），但不能少
    if (hpx < ch || hpx > ch + 8) {
      failures.push(`手机版纸张高 ${hpx}px 与图片高 ${ch}px 不匹配（应略大 1~4px）`);
    }
    if (wpx >= 794) failures.push(`手机版纸张宽 ${wpx}px，已达 A4 宽度，不是手机尺寸`);
  }
  mod.chooseView('mobile');   // 收尾留在手机版
})();

/* ---- 学期总览 ---- */
(function () {
  const countCourses = (h) => (h.match(/class="course"/g) || []).length;
  mod.chooseView('web');
  mod.chooseScope('week');
  mod.renderWeek(svgWeek);
  const weekCells = getEl('tbody').innerHTML;
  const nWeek = countCourses(weekCells);
  const weekTitleTxt = getEl('title').textContent;

  mod.chooseScope('overview');
  const ovCells = getEl('tbody').innerHTML;
  const nOv = countCourses(ovCells);

  if (nOv < nWeek) failures.push(`总览课程数 ${nOv} 不应少于单周的 ${nWeek}`);
  const ovT = mod.overviewTitle();
  if (getEl('title').textContent !== ovT) failures.push(`总览标题应为「${ovT}」，实得「${getEl('title').textContent}」`);
  if (!/学期课表总览/.test(ovT)) failures.push('总览标题应含「学期课表总览」');
  if (!/全学期共/.test(getEl('stat').textContent)) failures.push(`总览统计行不对：${getEl('stat').textContent}`);
  if (!/mode-overview/.test(document.body.className)) failures.push(`总览时 body 缺 mode-overview：${document.body.className}`);

  /* 同一格多门课：必须都写进去（只有数据里真有这种格子时才断言） */
  const rows = ovCells.split('</tr>').filter(x => x.includes('<tr'));
  let stacked = 0;
  rows.forEach(row => {
    (row.match(/<td[^>]*>[\s\S]*?<\/td>/g) || []).forEach(td => {
      const names = [...td.matchAll(/class="cname"[^>]*>([^<]*)</g)].map(x => x[1]);
      if (names.length >= 2) stacked++;
    });
  });
  const perSlot = {};
  DATA.courses.forEach(c => { const k = c.day + '|' + c.block; perSlot[k] = (perSlot[k] || 0) + 1; });
  const expectStack = Object.keys(perSlot).filter(k => perSlot[k] >= 2).length;
  if (expectStack && stacked === 0)
    failures.push(`数据里有 ${expectStack} 个「同一格多门课」，总览却没合并`);
  if (stacked > expectStack)
    failures.push(`总览合并出的多课格子数 ${stacked} 超过了数据里的 ${expectStack}`);
  if (countCourses(ovCells) !== DATA.courses.length)
    failures.push(`总览应画出全部 ${DATA.courses.length} 条课程，实际 ${countCourses(ovCells)}`);

  /* 总览的手机版要能分页 */
  mod.chooseView('mobile');
  const box = mod.setPrintPage();
  if (!/297mm/.test(getEl('pageStyle').textContent))
    failures.push(`总览手机版纸张应为手机宽 × 297mm，实得 ${getEl('pageStyle').textContent}`);
  if (box && box.pages < 1) failures.push('总览应标记为可能多页');
  if (!/111\.1mm/.test(getEl('pageStyle').textContent))
    failures.push('总览手机版纸张宽度应仍为手机宽度');

  mod.chooseView('web');
  mod.chooseScope('week');
  mod.renderWeek(svgWeek);
  if (/mode-overview/.test(document.body.className)) failures.push('切回按周后 body 仍带 mode-overview');
  if (getEl('title').textContent !== weekTitleTxt) failures.push('切回按周后标题没恢复');
})();

if (svgTable.indexOf('第 ' + svgWeek + ' 周') < 0 && svgTable.indexOf('第' + svgWeek + '周') < 0)
  failures.push('表格 SVG：标题里没有当前周次');
// 有课时必须真的画出了课程名
if (!results.every(r => r.gridHidden) && svgTable.indexOf(svgDays[0]) < 0)
  failures.push('表格 SVG：没有画表头星期');

/* --svg <dir>：把两个 SVG 落盘，便于用 XML 解析器做严格校验 */
const svgOut = argv.indexOf('--svg') >= 0 ? argv[argv.indexOf('--svg') + 1] : null;
if (svgOut) {
  fs.mkdirSync(svgOut, { recursive: true });
  fs.writeFileSync(path.join(svgOut, 'table-w' + svgWeek + '.svg'), svgTable);
  fs.writeFileSync(path.join(svgOut, 'cards-w' + svgWeek + '.svg'), svgCards);
  console.log('SVG 已写出: table-w' + svgWeek + '.svg / cards-w' + svgWeek + '.svg (第 ' + svgWeek + ' 周)');
}

/* ---------- 输出 ---------- */
if (asJson) {
  console.log(JSON.stringify({ data: { who: DATA.who, days: DATA.days, blocks: DATA.blocks, maxWeek: maxW },
                               overviewTitle: mod.overviewTitle(),
                               initialView: initialView, weeks: results, failures }, null, 1));
} else if (asMobile) {
  for (const r of results) {
    console.log('='.repeat(52));
    console.log(`${r.title}    [${r.stat}]`);
    if (r.gridHidden) { console.log('  （无课）'); continue; }
    r.mobile.forEach(m => {
      console.log(`  ┌ ${m.day}${m.cls.includes('weekend') ? '  (周末)' : ''}`);
      if (!m.names.length) { console.log('  │   无课'); return; }
      m.names.forEach((n, i) => console.log(`  │ ${m.pers[i].padStart(4)}  ${n}    ${m.metas[i] || ''}`));
    });
  }
  console.log('='.repeat(52));
  console.log(failures.length ? `✗ ${failures.length} 项断言失败:\n   - ` + failures.join('\n   - ')
                              : `✓ ${results.length} 周：手机版与电脑版内容一致，视图切换正常`);
} else {
  const days = usedDays;
  for (const r of results) {
    console.log('='.repeat(70));
    console.log(`${r.title}    [${r.stat}]`);
    if (r.gridHidden) { console.log('  （无课，页面显示：' + r.emptyBox.replace(/<[^>]+>/g, '') + '）'); continue; }
    for (const row of r.rows) {
      const parts = row.cells.map((cs, i) => cs.length
        ? `${days[i]}: ` + cs.map(c => `${c.name}${c.room ? '(' + c.room + ')' : ''}[${c.weeks}]`).join(' + ')
        : null).filter(Boolean);
      console.log(`  ${row.block.padEnd(5)} ${parts.length ? parts.join('  |  ') : '—'}`);
    }
  }
  console.log('='.repeat(70));
  if (failures.length) {
    console.log(`✗ ${failures.length} 项断言失败:`);
    failures.forEach(f => console.log('   - ' + f));
  } else {
    console.log(`✓ ${results.length} 周全部通过（统计行 / 行列数 / 下拉框同步 / 按钮置灰 / 无同时段双课 / 手机版与电脑版一致 / 视图切换）`);
  }
}
/* ---- 学期总览：可选打印出来核对 ---- */
if (argv.includes('--overview') && !asJson) {
  mod.chooseView('web');
  mod.chooseScope('overview');
  const tbody = getEl('tbody').innerHTML;
  const rows = tbody.split('</tr>').filter(r => r.includes('<tr')).map(r => parseRow(r + '</tr>'));
  console.log('');
  console.log('===== ' + getEl('title').textContent + '   [' + getEl('stat').textContent + '] =====');
  rows.forEach(row => {
    const parts = row.cells.map((cs, i) => cs.length
      ? usedDays[i] + ': ' + cs.map(c => `${c.name}${c.room ? '(' + c.room + ')' : ''}[${c.weeks}]`).join('  +  ')
      : null).filter(Boolean);
    console.log('  ' + row.block.padEnd(5) + ' ' + (parts.length ? parts.join('  |  ') : '—'));
  });
  console.log('同一格里多门课 = 用 " + " 连起来显示');
}

process.exit(failures.length ? 1 : 0);
