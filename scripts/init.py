#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zectrix-friday-weather 初始化向导

收集三项信息并写入 ~/.config/zectrix-friday-weather/config.json:
  1. Zectrix API Key（控制台获取，格式 zt_ 开头）
  2. 设备 ID（设备 MAC，如 AA:BB:CC:DD:EE:FF）
  3. 所在地区（中文地名，自动地理编码为经纬度，用于获取当地天气）

用法:
  python3 init.py                      # 交互式引导（推荐首次使用）
  python3 init.py --api-key zt_xxx --device AA:BB:CC:DD:EE:FF --place "成都成华区"
  python3 init.py --api-key zt_xxx --list-devices   # 只列出该 Key 下的设备
  python3 init.py --place "上海" --label "上海·徐汇"   # 只改地区(需已有配置)
所有参数都支持 --page 指定页码(1-5, 默认5)。
"""
import sys, os, json, argparse, subprocess, urllib.request, urllib.error, urllib.parse

CONFIG_DIR = os.environ.get("ZECTRIX_FRIDAY_CONFIG_DIR",
                            os.path.expanduser("~/.config/zectrix-friday-weather"))
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
BASE = "https://cloud.zectrix.com/open/v1"
GEO = "https://geocoding-api.open-meteo.com/v1/search"


def api(path, key=None):
    req = urllib.request.Request(BASE + path)
    req.add_header("User-Agent", "Mozilla/5.0")
    if key:
        req.add_header("X-API-Key", key)
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")


def curl_json(url):
    r = subprocess.run(["curl", "-s", "--max-time", "20", url],
                       capture_output=True, timeout=30)
    try:
        return json.loads(r.stdout.decode("utf-8", "ignore"))
    except Exception:
        return None


def input_required(prompt, secret=False):
    try:
        if secret:
            import getpass
            v = getpass.getpass(prompt)
        else:
            v = input(prompt)
    except EOFError:
        v = ""
    v = (v or "").strip()
    if not v:
        print("未提供，已取消。", file=sys.stderr)
        sys.exit(1)
    return v


def _geo_search(place, language="zh"):
    url = "%s?name=%s&count=8&language=%s&format=json" % (
        GEO, urllib.parse.quote(place), language)
    data = curl_json(url) or {}
    out = []
    for r in data.get("results", []) or []:
        name = r.get("name", "")
        admin1 = (r.get("admin1") or "").replace("省", "").replace("市", "")
        country = r.get("country", "")
        label = "%s·%s" % (name, admin1) if admin1 and admin1 != name else name
        if country and country not in ("中国", "China"):
            label = "%s·%s" % (label, country)
        out.append({"label": label, "lat": r.get("latitude"), "lon": r.get("longitude"),
                    "timezone": r.get("timezone", "auto"), "country": country})
    return out


def geocode(place, language="zh"):
    """地名 -> 候选列表。Open-Meteo 只收录到市/县一级，
    「成都成华区」这类细粒度地名逐级截短重试（成都成华区 → 成都成 → 成都）。"""
    out = _geo_search(place, language)
    if not out:
        for n in range(len(place) - 1, 1, -1):
            out = _geo_search(place[:n], language)
            if out:
                print("（地理编码无「%s」，已回退到「%s」）" % (place, place[:n]))
                break
    return out


def pick_location(place, label=None):
    cands = geocode(place)
    if not cands:
        print("地理编码失败：没找到「%s」，请换个更通用的地名（如「成都」「上海浦东」）。" % place,
              file=sys.stderr)
        sys.exit(3)
    if len(cands) == 1 or not sys.stdin.isatty():
        sel = cands[0]
    else:
        print("找到 %d 个匹配地点，请选一个：" % len(cands))
        for i, c in enumerate(cands):
            print("  %d) %s  (%.4f, %.4f) %s" % (i + 1, c["label"], c["lat"], c["lon"], c["country"]))
        while True:
            v = input("输入序号 [1]: ").strip() or "1"
            if v.isdigit() and 1 <= int(v) <= len(cands):
                sel = cands[int(v) - 1]
                break
            print("无效序号，重试。")
    sel = dict(sel)
    if label:
        sel["label"] = label
    return {"label": sel["label"], "lat": sel["lat"], "lon": sel["lon"],
            "timezone": sel["timezone"]}


def verify_device(key, device):
    st, body = api("/devices", key)
    if st != 200:
        print("API Key 校验失败 (HTTP %s): %s" % (st, body[:200]), file=sys.stderr)
        return False
    try:
        js = json.loads(body)
    except Exception:
        print("返回解析失败: %s" % body[:200], file=sys.stderr)
        return False
    if js.get("code") != 0:
        print("API Key 无效: %s" % body[:200], file=sys.stderr)
        return False
    data = js.get("data")
    if isinstance(data, list):            # 直接返回设备数组
        devs = data
    elif isinstance(data, dict):           # 包一层的情况
        devs = data.get("devices") or data.get("list") or []
    else:
        devs = []
    ids = [x.get("deviceId") or x.get("device_id") or x.get("mac")
           for x in devs if isinstance(x, dict)]
    if device and ids and device.upper() not in [i.upper() for i in ids if i]:
        print("警告：设备 %s 不在该 Key 的设备列表里（%s）" % (device, ", ".join(ids)), file=sys.stderr)
        print("如果确认设备号正确可忽略，但更可能是填错了。", file=sys.stderr)
        return False
    print("API Key 校验通过，共 %d 台设备。" % (len(ids) or 1))
    return True


def main():
    ap = argparse.ArgumentParser(description="zectrix-friday-weather 初始化")
    ap.add_argument("--api-key")
    ap.add_argument("--device")
    ap.add_argument("--place", help="所在地区，如 成都成华区 / 上海 / 北京朝阳")
    ap.add_argument("--label", help="屏上显示的地区名，默认自动组合，如 成都·成华")
    ap.add_argument("--page", default="5", help="推送到哪一页 1-5，默认 5")
    ap.add_argument("--list-devices", action="store_true", help="列出该 Key 下所有设备后退出")
    ap.add_argument("--no-verify", action="store_true", help="跳过 API Key/设备校验")
    args = ap.parse_args()

    old = {}
    if os.path.exists(CONFIG_FILE):
        try:
            old = json.load(open(CONFIG_FILE, encoding="utf-8"))
        except Exception:
            old = {}

    if args.list_devices:
        if not args.api_key:
            print("需要 --api-key", file=sys.stderr); sys.exit(1)
        st, body = api("/devices", args.api_key)
        print(body[:2000])
        return

    print("== zectrix-friday-weather 初始化 ==")
    print("需要三项信息：Zectrix API Key、设备 ID、所在地区（用于天气）。\n")

    key = args.api_key or old.get("api_key") or \
        input_required("1) Zectrix API Key（zt_ 开头，输入不回显）: ", secret=True)
    device = args.device or old.get("device_id") or \
        input_required("2) 设备 ID（MAC，如 AA:BB:CC:DD:EE:FF）: ")
    place = args.place
    if not place:
        cur = old.get("location", {}).get("label", "")
        place = input_required("3) 所在地区（如 成都成华区）%s: " % (("[保持 %s 请直接回车]" % cur) if cur else ""))

    if not args.no_verify:
        if not verify_device(key, device):
            print("\n提示：如确认信息无误，可加 --no-verify 强制写入。", file=sys.stderr)
            sys.exit(4)

    loc = pick_location(place, args.label)
    cfg = {
        "api_key": key,
        "device_id": device,
        "page": args.page,
        "location": loc,
        "updated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
    }
    os.makedirs(CONFIG_DIR, exist_ok=True)
    json.dump(cfg, open(CONFIG_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n已写入 %s" % CONFIG_FILE)
    print("  设备 : %s (第 %s 页)" % (device, args.page))
    print("  地区 : %s  (%.4f, %.4f) %s" % (loc["label"], loc["lat"], loc["lon"], loc["timezone"]))
    print("\n下一步：")
    print("  ZECTRIX_NO_PUSH=1 python3 scripts/zectrix_friday_push.py   # 先本地预览")
    print("  python3 scripts/zectrix_friday_push.py                     # 确认无误后推送")


if __name__ == "__main__":
    main()
