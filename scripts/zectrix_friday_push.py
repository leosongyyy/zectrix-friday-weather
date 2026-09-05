#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zectrix 墨水屏 —— 「今天是周五吗？」+ 本地天气（单页趣味屏）

黑白单色 400x300 墨水屏专用。左栏=周五趣味文案（按星期/时段切换文案池，洗牌袋不重复），
右栏=当地当天天气（大图标 + 大温度 + 状况 + 紫外线 + HI/LO），
下方=今明后三天预报 + 一条按实际天气生成的出行/穿搭建议。
文案与时段规则思路来自开源项目 eyaeya/today-is-friday (MIT)，本脚本为黑白屏重排版。

配置：~/.config/zectrix-friday-weather/config.json（由同目录 init.py 生成，不含任何硬编码密钥）
用法:
  python3 zectrix_friday_push.py          # 渲染并推送
  ZECTRIX_NO_PUSH=1 python3 zectrix_friday_push.py   # 只渲染不推送

依赖: pillow
"""
import sys, os, json, uuid, random, datetime, subprocess
import urllib.request, urllib.error
from PIL import Image, ImageDraw, ImageFont

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(SKILL_DIR, "assets", "fonts")
CONFIG_DIR = os.environ.get("ZECTRIX_FRIDAY_CONFIG_DIR",
                            os.path.expanduser("~/.config/zectrix-friday-weather"))
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
STATE_FILE = os.path.join(CONFIG_DIR, "state.json")
DATA_FILE = os.path.join(SKILL_DIR, "scripts", "friday_phrases.json")
PREVIEW = "/tmp/zectrix_friday_screen.png"

# ---------- 字体探测: 默认仓库自带点阵字体, 可 env 覆盖, 逐级回退 ----------
# 默认使用随仓库分发的 assets/fonts/Zfull.ttf 点阵字体（墨水屏像素级锐利，无需另装）。
# 想换字体时设置环境变量 ZECTRIX_FONT=/path/to/xxx.ttf 即可覆盖。
FONT_CANDIDATES = [
    os.environ.get("ZECTRIX_FONT", ""),
    os.path.join(FONT_DIR, "Zfull.ttf"),
    os.path.expanduser("~/Library/Fonts/Zfull.ttf"),
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]
FONT_PATH = next((p for p in FONT_CANDIDATES if p and os.path.exists(p)), None)

# ---------- 配置 ----------
def load_config():
    if not os.path.exists(CONFIG_FILE):
        print("NEED_INIT: 未找到配置文件 %s" % CONFIG_FILE, file=sys.stderr)
        print("请先运行 init.py 完成初始化（需要用户提供 Zectrix API Key、设备 ID 和所在地区）",
              file=sys.stderr)
        sys.exit(2)
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)

cfg = load_config()
KEY = cfg["api_key"]
DEV = cfg["device_id"]
PAGE = str(cfg.get("page", 5))
LOC = cfg["location"]                     # {"label":..., "lat":..., "lon":..., "timezone":...}
LAT, LON = LOC["lat"], LOC["lon"]
LABEL = LOC.get("label", "")
TZ = LOC.get("timezone", "auto")

# ---------- 时段规则 ----------
WD_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
WD_SHORT = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

def period(now):
    """返回 (文案池名, 开场语, 是否黑底反白, 是否画退朝章)"""
    wd, h = now.weekday(), now.hour
    if wd == 4:
        if h >= 16:
            return ("FridayEvening", "周五啦！", True, True)
        return ("FridayDay", "周五啦！", True, False)
    if wd == 5:
        return ("Saturday", "休息。", True, False)
    if wd == 6:
        if h >= 19:
            return ("SundayEvening", "明天周一。", False, False)
        return ("SundayDay", "休息。", True, False)
    pool = ["Monday", "Tuesday", "Wednesday", "Thursday"][wd]
    return (pool, "不是。", False, False)

# ---------- 洗牌袋选文案 ----------
def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(st):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)

def pick_phrase(pool):
    with open(DATA_FILE, encoding="utf-8") as f:
        ph = json.load(f)[pool]
    n = len(ph)
    st = load_state()
    bag = st.get("bags", {}).get(pool)
    refill = not bag
    if refill:
        bag = list(range(n))
        random.shuffle(bag)
    idx = bag.pop(0)
    if refill and bag and idx == st.get("last_idx", {}).get(pool):
        bag.append(idx)
        idx = bag.pop(0)
    st.setdefault("bags", {})[pool] = bag
    st.setdefault("last_idx", {})[pool] = idx
    save_state(st)
    return ph[idx]

# ---------- 天气 (Open-Meteo, 免费无需申请 key) ----------
WMO = {0:"晴", 1:"晴", 2:"多云", 3:"阴", 45:"雾", 48:"雾",
       51:"小雨", 53:"小雨", 55:"中雨", 56:"冻雨", 57:"冻雨",
       61:"小雨", 63:"中雨", 65:"大雨", 66:"冻雨", 67:"冻雨",
       71:"小雪", 73:"中雪", 75:"大雪", 77:"雪粒",
       80:"阵雨", 81:"阵雨", 82:"强阵雨", 85:"阵雪", 86:"阵雪",
       95:"雷雨", 96:"雷雨", 99:"雷雨"}
RAIN = {51,53,55,56,57,61,63,65,66,67,80,81,82,95,96,99}
SNOW = {71,73,75,77,85,86}

def fetch_weather():
    url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
           "&current_weather=true&daily=temperature_2m_max,temperature_2m_min,weather_code,uv_index_max"
           "&timezone=%s&forecast_days=3" % (LAT, LON, TZ))
    try:
        r = subprocess.run(["curl", "-s", "--max-time", "20", url],
                           capture_output=True, timeout=30)
        return json.loads(r.stdout.decode("utf-8", "ignore"))
    except Exception:
        return None

# ---------- 渲染 ----------
W, H = 400, 300
IW, IH = W, H

def F(sz):
    if FONT_PATH:
        return ImageFont.truetype(FONT_PATH, sz)
    return ImageFont.load_default()

img = Image.new("L", (IW, IH), 255)
d = ImageDraw.Draw(img)
M = 14

now = datetime.datetime.now()
pool, answer, invert, stamp = period(now)
phrase = pick_phrase(pool)
wx = fetch_weather()

f_q = F(19)      # 问题
f_ans = F(34)    # 开场语
f_line = F(19)   # 文案两行
f_cond = F(14)   # 天气状况
f_hilo = F(12)   # HI/LO
f_cell_d = F(12) # 预报格星期
f_cell_t = F(14) # 预报格温度
f_tip = F(12)    # 提示条
f_meta = F(13)   # 顶部地址/底部日期

tcol = 255 if invert else 0  # 主框内文字颜色(快乐日黑底反白)

# 顶部问题(左上角) + 天气地址(右上角)
d.text((M, 24), "今天是周五吗？", font=f_q, fill=0, anchor="lm")
if LABEL:
    d.text((IW - M, 24), LABEL, font=f_meta, fill=0, anchor="rm")

# 主内容大边框(左=周五内容, 右=当天天气; 快乐日整框黑底)
fx0, fy0, fx1, fy1 = M, 42, IW - M, 164
if invert:
    d.rectangle([fx0, fy0, fx1, fy1], fill=0)
d.rectangle([fx0, fy0, fx1, fy1], outline=0, width=3)
div_x = 228
d.line([(div_x, fy0 + 8), (div_x, fy1 - 8)], fill=tcol, width=2)

tx = fx0 + 16  # 左栏左对齐基准
d.text((tx, 70), answer, font=f_ans, fill=tcol, anchor="lm")
d.text((tx, 112), phrase["line1"], font=f_line, fill=tcol, anchor="lm")
d.text((tx, 138), phrase["line2"], font=f_line, fill=tcol, anchor="lm")

# 右栏: 当天天气
def draw_icon(cx, cy, s, code, col):
    """e-ink 天气站风格: 粗描边蓬云 + 云后探日, 以(cx,cy)为中心"""
    lw = 4 if s >= 40 else 2
    bg = 255 - col

    def sun(sx, sy, sr):
        d.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], outline=col, width=lw)
        import math
        for k in range(8):
            a = k * math.pi / 4
            x1, y1 = sx + sr * 1.35 * math.cos(a), sy + sr * 1.35 * math.sin(a)
            x2, y2 = sx + sr * 1.85 * math.cos(a), sy + sr * 1.85 * math.sin(a)
            d.line([(x1, y1), (x2, y2)], fill=col, width=lw)

    def cloud(dx, dy, w):
        # 两遍绘制(先外扩描边色再填背景色): 得到无内线的粗轮廓, 并遮挡云后太阳
        puffs = [
            [dx - 0.50 * w, dy - 0.16 * w, dx - 0.02 * w, dy + 0.26 * w],
            [dx - 0.30 * w, dy - 0.40 * w, dx + 0.20 * w, dy + 0.24 * w],
            [dx - 0.04 * w, dy - 0.26 * w, dx + 0.50 * w, dy + 0.26 * w],
        ]
        base = [dx - 0.46 * w, dy + 0.06 * w, dx + 0.46 * w, dy + 0.30 * w]
        for pad, fill in ((lw, col), (0, bg)):
            for b in puffs:
                d.ellipse([b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad], fill=fill)
            d.rectangle([base[0] - pad, base[1], base[2] + pad, base[3] + pad], fill=fill)

    if code in (0, 1):
        sun(cx, cy, s * 0.30)
    elif code == 2:
        sun(cx - 0.18 * s, cy - 0.30 * s, s * 0.20)
        cloud(cx + 0.06 * s, cy + 0.08 * s, s * 0.80)
    else:
        cloud(cx, cy - 0.05 * s, s * 0.88)
        if code in (95, 96, 99):      # 雷雨
            k = s * 0.011
            bolt = [(6, 22), (-8, 38), (0, 38), (-10, 52), (10, 34), (2, 34), (12, 22)]
            d.polygon([(cx + px * k, cy + py * k) for px, py in bolt], fill=col)
        elif code in RAIN:            # 雨
            for rx in (-0.2, 0.0, 0.2):
                x = cx + s * rx
                d.line([(x, cy + s * 0.32), (x - s * 0.05, cy + s * 0.44)], fill=col, width=lw)
        elif code in SNOW:            # 雪
            sr = 3 if s >= 40 else 2
            for rx, ry in ((-0.2, 0.38), (0.02, 0.44), (0.22, 0.36)):
                x, y = cx + s * rx, cy + s * ry
                d.ellipse([x - sr, y - sr, x + sr, y + sr], fill=col)
        elif code in (45, 48):        # 雾
            for i, ry in enumerate((0.34, 0.44)):
                off = s * 0.04 if i else 0
                d.line([(cx - s * 0.26 + off, cy + s * ry),
                        (cx + s * 0.26 - off, cy + s * ry)], fill=col, width=lw)

uv = None
if wx and "current_weather" in wx:
    cw = wx["current_weather"]
    dl = wx["daily"]
    cur_t = round(cw["temperature"])
    cur_c = cw.get("weathercode", 0)
    tmax = [round(v) for v in dl["temperature_2m_max"]]
    tmin = [round(v) for v in dl["temperature_2m_min"]]
    codes = dl["weather_code"]
    uv_raw = (dl.get("uv_index_max") or [None])[0]
    uv = round(uv_raw) if uv_raw is not None else None

    cx2 = (div_x + fx1) / 2  # 右栏中心
    # 大图标 + 大温度并排, 整体在右栏水平居中
    icon_w = 66 if cur_c in (0, 1) else 58
    gap = 8
    temp_str = "%d°" % cur_t
    tsz = 48
    avail = fx1 - 10 - (div_x + 10) - icon_w - gap
    while tsz > 26 and d.textlength(temp_str, font=F(tsz)) > avail:
        tsz -= 4
    tw = d.textlength(temp_str, font=F(tsz))
    sx0 = cx2 - (icon_w + gap + tw) / 2
    d.text((sx0 + icon_w + gap, 90), temp_str, font=F(tsz), fill=tcol, anchor="lm")
    draw_icon(sx0 + icon_w / 2, 90, 54, cur_c, tcol)

    # 状况 + 紫外线等级
    def uv_level(u):
        if u is None: return None
        if u >= 11: return "极强"
        if u >= 8: return "很强"
        if u >= 6: return "强"
        if u >= 3: return "中等"
        return "弱"
    cond_txt = WMO.get(cur_c, "—")
    if uv is not None:
        cond_txt = "%s  UV%d %s" % (cond_txt, uv, uv_level(uv))
    d.text((cx2, 132), cond_txt, font=f_cond, fill=tcol, anchor="mm")
    d.text((cx2, 152), "HI %d°  LO %d°" % (tmax[0], tmin[0]), font=f_hilo, fill=tcol, anchor="mm")
else:
    cx2 = (div_x + fx1) / 2
    d.text((cx2, 100), "天气", font=f_cond, fill=tcol, anchor="mm")
    d.text((cx2, 124), "获取失败", font=f_cond, fill=tcol, anchor="mm")
    tmax = tmin = codes = None

# 周五傍晚「退朝」印章(压在主框右上角边框上)
if stamp:
    r = 24
    sx, sy = div_x - 34, fy0 + 22
    d.ellipse([sx - r, sy - r, sx + r, sy + r], outline=tcol, width=3)
    d.ellipse([sx - r + 4, sy - r + 4, sx + r - 4, sy + r - 4], outline=tcol, width=1)
    seal = Image.new("L", (80, 80), 255)
    sd = ImageDraw.Draw(seal)
    sd.text((40, 40), "退朝", font=F(20), fill=0, anchor="mm")
    seal = seal.rotate(12, resample=Image.BICUBIC, fillcolor=255)
    img.paste(tcol, (sx - 40, sy - 40), seal.point(lambda p: 255 - p))

# 今明后三天预报格
if tmax is not None:
    labels = ["今天", "明天", WD_SHORT[(now.weekday() + 2) % 7]]
    cw_box = (IW - 2 * M - 2 * 10) / 3
    by0, by1 = 176, 232
    for i in range(3):
        bx0 = M + i * (cw_box + 10)
        d.rectangle([bx0, by0, bx0 + cw_box, by1], outline=0, width=2)
        bcx = bx0 + cw_box / 2
        d.text((bcx, by0 + 15), labels[i], font=f_cell_d, fill=0, anchor="mm")
        d.text((bcx, by0 + 40), "%d° / %d°" % (tmax[i], tmin[i]), font=f_cell_t, fill=0, anchor="mm")

# 提示条: 按实际天气给出行/穿搭建议(黑底白字)
tip = None
if codes is not None:
    if codes[0] in RAIN:
        tip = "今天有雨，带伞穿防水的鞋"
    elif codes[1] in RAIN:
        if tmax[1] >= 33:
            tip = "明天有雨仍闷热，带伞穿透气短袖"
        elif tmin[1] <= 12:
            tip = "明天有雨降温，带伞加件外套"
        else:
            tip = "明天有雨，出门记得带伞"
    elif codes[0] in SNOW or codes[1] in SNOW:
        tip = "近期有雪，注意保暖防滑"
    elif tmax[0] >= 35:
        tip = "今日高温，短袖防晒勤补水"
    elif tmin[0] <= 5:
        tip = "气温偏低，出门穿件厚外套"
    elif tmax[0] - tmin[0] >= 12:
        tip = "昼夜温差大，早晚添件外套"

if uv is not None and uv >= 6:
    if tip is None:
        tip = "紫外线很强，出门涂防晒霜" if uv >= 8 else "紫外线较强，建议涂防晒"
    elif "防晒" not in tip and len(tip) <= 14:
        tip += "，记得涂防晒"
elif codes is not None and tip is None:
    if codes[0] in (0, 1, 2) and 18 <= tmax[0] <= 32:
        tip = "天气不错，适合外出走走"

if tip:
    d.rectangle([M, 242, IW - M, 264], fill=0)
    d.text((IW / 2, 253), tip, font=f_tip, fill=255, anchor="mm")

# 框外底部: 日期居左 星期居右
d.text((M, 282), "%d年%d月%d日" % (now.year, now.month, now.day), font=f_meta, fill=0, anchor="lm")
d.text((IW - M, 282), WD_CN[now.weekday()], font=f_meta, fill=0, anchor="rm")

THRESHOLD = 128  # 二值化阈值(墨水屏偏粗更清晰)
final = img.point(lambda p: 0 if p < THRESHOLD else 255).convert("RGB")
final.save(PREVIEW)
print("saved %s | 池=%s 开场=%s 文案=%s/%s | 天气=%s | 字体=%s" %
      (PREVIEW, pool, answer, phrase["line1"], phrase["line2"],
       ("%d° %s UV%s" % (round(wx["current_weather"]["temperature"]),
                         WMO.get(wx["current_weather"].get("weathercode", 0), "?"), uv))
       if wx else "失败", os.path.basename(FONT_PATH or "default")))

# ---------- 推送 ----------
BASE = "https://cloud.zectrix.com/open/v1"

def multipart(path, fields, files):
    boundary = ("----WebKitFormBoundary" + uuid.uuid4().hex[:16]).encode()
    body = b""
    for k, v in fields.items():
        body += b"--" + boundary + b"\r\n"
        body += ('Content-Disposition: form-data; name="%s"' % k).encode() + b"\r\n\r\n"
        body += str(v).encode() + b"\r\n\r\n"
    for k, fn, ct, data in files:
        body += b"--" + boundary + b"\r\n"
        body += ('Content-Disposition: form-data; name="%s"; filename="%s"' % (k, fn)).encode() + b"\r\n"
        body += ('Content-Type: %s' % ct).encode() + b"\r\n\r\n"
        body += data + b"\r\n"
    body += b"--" + boundary + b"--\r\n"
    req = urllib.request.Request(BASE + path, data=body, method="POST")
    req.add_header("X-API-Key", KEY)
    req.add_header("User-Agent", "Mozilla/5.0")
    req.add_header("Content-Type", "multipart/form-data; boundary=" + boundary.decode())
    try:
        r = urllib.request.urlopen(req, timeout=40)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

if os.environ.get("ZECTRIX_NO_PUSH") == "1":
    print("ZECTRIX_NO_PUSH=1, 跳过推送")
    sys.exit(0)

with open(PREVIEW, "rb") as f:
    fb = f.read()
st, body = multipart("/devices/%s/display/image" % DEV,
                     {"pageId": PAGE, "dither": "false"},
                     [("images", "friday.png", "image/png", fb)])
print("PUSH pageId=%s -> %s %s" % (PAGE, st, body[:200]))
