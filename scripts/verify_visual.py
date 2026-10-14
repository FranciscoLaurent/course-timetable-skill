#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可选自检：用本机浏览器把课表**真的渲染一遍**，量关键几何，需要时才出图。

用法:
    python verify_visual.py 课表.html                  # 默认两档：手机版舞台 + 真机 390，只量不存图
    python verify_visual.py 课表.html --all            # 五档场景全跑
    python verify_visual.py 课表.html --shot 目录      # 额外把 PNG 存到该目录
    python verify_visual.py 课表.html --browser 路径   # 手动指定浏览器

退出码:
    0 = 几何全部通过，**或本机没有可用浏览器**（跳过，并打印人工目测清单）
    1 = 量到越界（有元素超出视口）

设计约束（重要）:
  * **永不阻塞交付**：找不到浏览器、沙箱不允许启动、超时 —— 一律当作"跳过"，退出码 0。
  * **默认不落任何文件**：截图先写临时目录，只有 `--shot` 才拷出来；中间产物跑完即删。
  * **不依赖 CDP**：只用 `--headless --screenshot`（Chrome / Edge / Chromium / Firefox 都支持）。
  * **窄视口靠 iframe**：无头 Chrome 的窗口最窄约 526px，直接 `--window-size=390` 会被
    按 526px 排版再裁图，看着像"被切"其实没切。所以把页面放进固定宽度的 iframe 里渲染，
    页面在 iframe 内部拿到的 innerWidth 才是真值。
  * 页面通过本地 http 服务加载（同源），因此量测代码能读 iframe 的 DOM，
    也就不需要 `--allow-file-access-from-files` 这类放宽安全的开关。

只依赖 Python 3 标准库。
"""
import json, os, shutil, subprocess, sys, tempfile, threading, time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True          # 别在 skill 目录里留下 __pycache__
from build_timetable import unique_out_path, SpecError   # noqa: E402

# 场景：名字 → (CSS 宽, CSS 高, 查询串)
SCENARIOS = {
    'web':      (1400, 900, '?view=web'),
    'mobile':   (1400, 800, '?view=mobile'),
    'phone':    (390,  844, '?view=mobile'),
    'short':    (1280, 700, '?view=mobile'),
    'overview': (1400, 800, '?view=mobile&scope=overview'),
}
DEFAULT_SCENARIOS = ['mobile', 'phone']
ALL_SCENARIOS = ['web', 'mobile', 'phone', 'short', 'overview']

BROWSER_NAMES = ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser',
                 'chrome', 'msedge', 'microsoft-edge', 'brave-browser', 'firefox']
WIN_PATHS = [
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Mozilla Firefox\firefox.exe',
]
NIX_PATHS = [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/Applications/Firefox.app/Contents/MacOS/firefox',
    '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
    '/usr/bin/firefox', '/snap/bin/chromium',
]

CHECKLIST = """
本机没有可用的浏览器（Chrome / Edge / Chromium / Firefox 都没找到，或沙箱不允许启动），
**视觉部分改为人工确认 —— 30 秒就够**（打开课表 HTML）：

  ① 下拉几个周次，看课程、时间、周次对不对
  ② 切「手机版」：机身下沿的黑色外框 + 圆角是否完整可见（不要被屏幕底边切掉）
  ③ 切「学期总览」：同一格里有多门课时，是否都显示出来了
  ④ 点「导出 PDF」→ 打印目标选「另存为 PDF」→ 是不是一页装下
  ⑤ 点「导出图片」→ 存下来的 PNG 是不是当前视图

另一条更省事的路：把课表 HTML 发到手机上打开，你看到的就是最终效果。
""".strip()


# ────────────────────────── 找浏览器 ──────────────────────────
def find_browser(explicit=None):
    if explicit:
        return explicit if os.path.exists(explicit) else None
    for env in ('DSH_BROWSER', 'CHROME_BIN', 'CHROMIUM_BIN', 'FIREFOX_BIN'):
        p = os.environ.get(env)
        if p and os.path.exists(p):
            return p
    for name in BROWSER_NAMES:
        p = shutil.which(name)
        if p:
            return p
    try:
        import winreg
        keys = [r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe',
                r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe']
        for sub in keys:
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(hive, sub) as k:
                        p = winreg.QueryValueEx(k, '')[0]
                    if os.path.exists(p):
                        return p
                except OSError:
                    pass
    except Exception:
        pass
    for p in WIN_PATHS + NIX_PATHS:
        if os.path.exists(p):
            return p
    return None


# ────────────────────────── 本地服务 ──────────────────────────
class ReportHandler(SimpleHTTPRequestHandler):
    """既当静态服务器，又收页面回传的量测结果。"""
    reports = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        if self.path == '/report':
            n = int(self.headers.get('Content-Length') or 0)
            try:
                ReportHandler.reports.append(json.loads(self.rfile.read(n).decode('utf-8')))
            except Exception:
                pass
            self.send_response(204)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()


HARNESS = """<!doctype html><meta charset="utf-8">
<style>html,body{{margin:0;background:#fff}}iframe{{width:{w}px;height:{h}px;border:0;display:block}}</style>
<iframe id="f" src="page.html{q}"></iframe>
<script>
document.getElementById('f').addEventListener('load', function(){{
  var w = this.contentWindow, d = this.contentDocument, o = {{}};
  function R(sel){{ var e = d.querySelector(sel); if (!e) return null;
    var r = e.getBoundingClientRect();
    return {{l:Math.round(r.left), r:Math.round(r.right), t:Math.round(r.top),
             b:Math.round(r.bottom), w:Math.round(r.width), h:Math.round(r.height)}}; }}
  function txt(sel){{ var e = d.querySelector(sel); return e ? (e.textContent || '').trim() : ''; }}
  o.scenario = {name!r};
  o.vw = w.innerWidth; o.vh = w.innerHeight;
  o.scrollW = d.documentElement.scrollWidth;
  o.scrollH = d.documentElement.scrollHeight;
  o.bar = R('.bar');
  o.phone = R('.phone');
  o.phoneShown = !!d.querySelector('.phone') &&
                 w.getComputedStyle(d.querySelector('.phoneWrap')).display !== 'none';
  o.title = txt('#title');
  o.stat = txt('#stat');
  o.courses = d.querySelectorAll('#tbody .course').length;
  try {{ fetch('/report', {{method:'POST', body: JSON.stringify(o)}}); }} catch (e) {{}}
}});
</script>
"""


def browser_cmd(browser, url, shot, w, h, profile):
    """组装命令行。外窗口要放得下 iframe：无头 Chrome 的窗口本身有最小宽度。"""
    outer_w = max(w + 20, 560)
    outer_h = h + 40
    if 'firefox' in os.path.basename(browser).lower():
        return [browser, '--headless', '--window-size=%d,%d' % (outer_w, outer_h),
                '--screenshot', shot, url]
    return [browser, '--headless', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
            '--no-default-browser-check', '--user-data-dir=' + profile,
            '--window-size=%d,%d' % (outer_w, outer_h),
            '--virtual-time-budget=4000', '--screenshot=' + shot, url]


def run_scenario(browser, name, tmp, shot_dir, port, profile):
    w, h, q = SCENARIOS[name]
    serve_dir = os.path.join(tmp, 'srv')
    harness = os.path.join(serve_dir, 'h_%s.html' % name)
    with open(harness, 'w', encoding='utf-8') as f:
        f.write(HARNESS.format(w=w, h=h, q=q, name=name))
    url = 'http://127.0.0.1:%d/h_%s.html' % (port, name)
    shot = os.path.join(tmp, 'shot_%s.png' % name)

    before = len(ReportHandler.reports)
    try:
        proc = subprocess.Popen(browser_cmd(browser, url, shot, w, h, profile),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:                       # 沙箱不让启动等
        return None, '启动失败: %s' % str(e)[:80], None

    deadline = time.time() + 45
    rep = None
    while time.time() < deadline:
        if len(ReportHandler.reports) > before:
            rep = ReportHandler.reports[-1]
            break
        if proc.poll() is not None:              # 浏览器退出了，再给请求 1 秒落地
            time.sleep(1.0)
            if len(ReportHandler.reports) > before:
                rep = ReportHandler.reports[-1]
            break
        time.sleep(0.2)
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

    saved = None
    if shot_dir and os.path.exists(shot):
        os.makedirs(shot_dir, exist_ok=True)
        # 与 build_timetable 共用同一条"绝不覆盖"规则：同名就自动让开
        target, _ = unique_out_path(os.path.join(shot_dir, '课表预览_%s.png' % name))
        shutil.copy(shot, target)
        saved = target
    if rep:
        return rep, None, saved
    return None, '没拿到量测结果（浏览器超时或直接退出）', saved


def check(rep):
    """只保留稳的判据：横向溢出、顶栏越界、机身被裁。

    注意区分两种形态：
      * **固定舞台**（宽屏下的"手机版"）：页面 height:100vh + overflow:hidden，翻不动页，
        所以机身一旦超出视口就是真被裁了 —— 这一档才检查机身上下沿。
      * **真机长页**（≤560px）：body 高度 auto、页面可滚动，机身比视口高是正常的，
        只检查横向溢出。
    """
    bad = []
    if rep['scrollW'] > rep['vw'] + 1:
        bad.append('横向溢出：scrollWidth=%d > 视口宽 %d' % (rep['scrollW'], rep['vw']))
    if rep.get('bar') and rep['bar']['r'] > rep['vw'] + 1:
        bad.append('顶栏右边超出视口：%d > %d' % (rep['bar']['r'], rep['vw']))
    page_scrolls = rep.get('scrollH', 0) > rep['vh'] + 1
    if rep.get('phoneShown') and rep.get('phone') and not page_scrolls:
        p = rep['phone']
        if p['b'] > rep['vh'] + 1:
            bad.append('机身下沿被裁：底边 %d > 视口高 %d' % (p['b'], rep['vh']))
        if p['t'] < -1:
            bad.append('机身上沿被裁：顶边 %d < 0' % p['t'])
    return bad


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    shot_dir = None
    browser_arg = None
    names = None
    rest = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--all':
            names = ALL_SCENARIOS
        elif a == '--shot':
            i += 1
            shot_dir = argv[i] if i < len(argv) else None
        elif a == '--browser':
            i += 1
            browser_arg = argv[i] if i < len(argv) else None
        elif a in ('-h', '--help'):
            print(__doc__)
            return 0
        else:
            rest.append(a)
        i += 1
    if len(rest) != 1:
        print(__doc__)
        return 2
    html = rest[0]
    if not os.path.exists(html):
        print('✗ 找不到文件: %s' % html)
        return 2

    names = names or DEFAULT_SCENARIOS
    print('视觉自检（可选）：%s' % os.path.basename(html))
    browser = find_browser(browser_arg)
    if not browser:
        print('— 跳过（本机没有可用浏览器）\n')
        print(CHECKLIST)
        return 0
    print('浏览器   : %s' % browser)

    tmp = tempfile.mkdtemp(prefix='timetable_visual_')
    serve_dir = os.path.join(tmp, 'srv')
    os.makedirs(serve_dir, exist_ok=True)
    shutil.copy(html, os.path.join(serve_dir, 'page.html'))     # 简化成 ASCII 名，URL 干净

    httpd = ThreadingHTTPServer(('127.0.0.1', 0),
                                partial(ReportHandler, directory=serve_dir))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    profile = os.path.join(tmp, 'profile')

    failed, skipped, saved_shots = [], [], []
    try:
        for name in names:
            w, h, _ = SCENARIOS[name]
            rep, err, saved = run_scenario(browser, name, tmp, shot_dir, port, profile)
            if saved:
                saved_shots.append(saved)
            if not rep:
                skipped.append('%s：%s' % (name, err))
                print('  %-9s %4d×%-4d  ⚠ %s' % (name, w, h, err))
                continue
            bad = check(rep)
            mark = '✓' if not bad else '⚠'
            scrolls = '可滚动长页' if rep.get('scrollH', 0) > rep['vh'] + 1 else '固定舞台'
            print('  %-9s %4d×%-4d  %s  视口 %d×%d  scrollW=%d  %s  课程块=%d  %s'
                  % (name, w, h, mark, rep['vw'], rep['vh'], rep['scrollW'],
                     scrolls, rep['courses'], rep.get('title', '')))
            for b in bad:
                print('        ⚠ %s' % b)
                failed.append('%s：%s' % (name, b))
    finally:
        httpd.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if saved_shots:
        print('图片已存到: %s' % os.path.dirname(saved_shots[0]))
        for s in saved_shots:
            print('   %s' % os.path.basename(s))
    if failed:
        print('✗ 发现 %d 处几何越界:' % len(failed))
        for f in failed:
            print('   -', f)
        return 1
    if skipped and len(skipped) == len(names):
        print('— 本机没能跑起来浏览器（已跳过），请按下面的清单人工看一眼：\n')
        print(CHECKLIST)
        return 0
    print('✓ 几何检查通过（没有横向溢出，机身/顶栏都在视口内）')
    if skipped:
        print('  （%d 档跳过：%s）' % (len(skipped), '；'.join(skipped)))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
