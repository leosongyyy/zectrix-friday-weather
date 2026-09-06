#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
渲染一张固定条件的示例图，用于 README / 文档展示（不推送、不依赖真实天气）。
默认渲染「周五傍晚 18:30」：黑底反白 + 右上的「退朝」印章 + 多云图标。

用法:
  python3 dev_render_sample.py [--out ../assets/sample-friday.png]
                               [--hour 18] [--weekday 4] [--code 2] [--temp 26] [--uv 6]
weekday: 0=周一 ... 4=周五, 5=周六, 6=周日（hour>=16 的周五会带「退朝」印章）
"""
import os, sys, json, argparse, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "zectrix_friday_push.py")

ap = argparse.ArgumentParser()
ap.add_argument("--out", default=os.path.join(HERE, "..", "assets", "sample-friday.png"))
ap.add_argument("--hour", type=int, default=18)
ap.add_argument("--weekday", type=int, default=4)
ap.add_argument("--code", type=int, default=2, help="WMO 天气码, 2=多云 0=晴 61=小雨 71=小雪")
ap.add_argument("--temp", type=int, default=26)
ap.add_argument("--uv", type=int, default=6)
ap.add_argument("--date", default="2026-09-11", help="示例日期 YYYY-MM-DD")
ap.add_argument("--label", default="示例市·示范区", help="示例图右上角地名(脱敏用)")

args = ap.parse_args()
os.environ["ZECTRIX_NO_PUSH"] = "1"

y, m, d = [int(x) for x in args.date.split("-")]
fake_now = "datetime.datetime(%d, %d, %d, %d, 30)" % (y, m, d, args.hour)
fake_wx = json.dumps({
    "current_weather": {"temperature": args.temp, "weathercode": args.code},
    "daily": {"temperature_2m_max": [args.temp + 2, args.temp + 3, args.temp + 1],
              "temperature_2m_min": [args.temp - 7, args.temp - 6, args.temp - 8],
              "weather_code": [args.code, 3, 0],
              "uv_index_max": [args.uv, 5, 6]},
})

src = open(SRC, encoding="utf-8").read()
src = src.replace("now = datetime.datetime.now()", "now = %s" % fake_now)
src = src.replace("wx = fetch_weather()", "wx = %s" % fake_wx)
src = src.replace('PREVIEW = "/tmp/zectrix_friday_screen.png"',
                  'PREVIEW = %r' % os.path.abspath(args.out))
src = src.replace('LABEL = LOC.get("label", "")', 'LABEL = %r' % args.label)

try:
    exec(compile(src, "sample_render", "exec"),
         {"__name__": "__main__", "__file__": SRC})
except SystemExit:
    pass
print("示例图已生成:", os.path.abspath(args.out))
