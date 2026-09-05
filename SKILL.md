---
name: zectrix-friday-weather
description: Zectrix 墨水屏「今天是周五吗？」趣味屏 + 当地天气单页推送。左栏按星期/时段切换文案池，右栏大图标+大温度+紫外线，下方三天预报与出行穿搭建议。首次使用引导用户提供 API Key、设备 ID 和所在地区。触发词：周五屏、周五吗、today is friday、墨水屏天气屏、推送周五屏、zectrix friday。
agent_created: true
---

# 墨水屏「今天是周五吗？」+ 天气屏

给 **Zectrix 400×300 单色墨水屏**渲染一页趣味屏，思路来自开源项目 [eyaeya/today-is-friday](https://github.com/eyaeya/today-is-friday)（MIT），本技能为黑白单色屏重新排版，并叠加了当地天气。

效果见 `assets/preview.png`：

- **顶部**：左「今天是周五吗？」，右显示用户所在地区（如「成都·成华区」）
- **左栏**：开场语 + 两行趣味文案，按星期/时段切换文案池，洗牌袋选句（一轮内不重复）
- **右栏**：大天气图标 + 大温度 + 状况 + **紫外线等级** + HI/LO
- **下方**：今/明/后三天预报格 + 一条按真实天气生成的出行穿搭建议（雨天带伞、高温防晒、低温添衣、温差提醒、紫外线涂防晒霜）

时段与配色规则（照搬原项目逻辑）：

| 时间 | 开场语 | 配色 |
|------|--------|------|
| 周一–周四 | 不是。 | 白底黑字 |
| 周五 16:00 前 | 周五啦！ | 黑底反白 |
| 周五 16:00 后 | 周五啦！+ 右上「退朝」印章 | 黑底反白 |
| 周六、周日 19:00 前 | 休息。 | 黑底反白 |
| 周日 19:00 后 | 明天周一。 | 白底黑字 |

> 文案池 9 个（周一~周四 / 周五白天 / 周五晚 / 周六 / 周日白天 / 周日晚），每池 65 条，存 `scripts/friday_phrases.json`，可直接往里加句子扩充。

## 一、首次使用：必须初始化（脱敏，无内置密钥）

本技能**不含任何 API Key、设备号或坐标**，全部由用户自备，首次运行前必须初始化。

```bash
cd ~/.workbuddy/skills/zectrix-friday-weather/scripts
python3 init.py            # 交互式引导，推荐
# 或非交互：
python3 init.py --api-key zt_xxx --device AA:BB:CC:DD:EE:FF --place "成都成华区" --label "成都·成华区"
```

需要向用户收集三样东西，缺一不可（**不要猜、不要用示例值**）：

1. **Zectrix API Key**：用户在极趣云控制台获取，`zt_` 开头。不确定可先跑 `python3 init.py --api-key zt_xxx --list-devices` 看能否列出设备。
2. **设备 ID**：设备 MAC，形如 `AA:BB:CC:DD:EE:FF`；上一条命令的输出里可取。
3. **所在地区**：中文地名，如「成都成华区」「上海徐汇」「深圳南山」。脚本会调 Open-Meteo 地理编码服务解析成经纬度；多个候选时交互选择，非交互环境默认取第一个。

初始化会校验 Key 与设备是否匹配（不匹配会警告并退出，确认识别问题可加 `--no-verify`），随后写入 `~/.config/zectrix-friday-weather/config.json`：

```json
{
  "api_key": "zt_xxx",
  "device_id": "AA:BB:CC:DD:EE:FF",
  "page": "5",
  "location": {"label": "XX·XX区", "lat": 30.0000, "lon": 104.0000, "timezone": "Asia/Shanghai"}
}
```

配置与状态都在 `~/.config/zectrix-friday-weather/`（可用环境变量 `ZECTRIX_FRIDAY_CONFIG_DIR` 覆盖），**不在技能目录内**，所以技能可以安全分享/更新而不泄露密钥。

## 二、日常使用

```bash
cd ~/.workbuddy/skills/zectrix-friday-weather/scripts
ZECTRIX_NO_PUSH=1 python3 zectrix_friday_push.py   # 只渲染预览，出图 /tmp/zectrix_friday_screen.png
python3 zectrix_friday_push.py                     # 渲染并推送到墨水屏
```

若未初始化，脚本会打印 `NEED_INIT:` 并以退出码 2 结束——此时按上一节引导用户补配置信息，不要自行编造 Key。

## 三、渲染与排版经验（改样式时务必遵守）

- **原生 400×300、1:1 渲染**，不要再放大后缩小；二值化阈值 `THRESHOLD=128`，`dither=false` 推送（硬阈值，文字最锐利）
- **字体**：自动探测顺序为 `$ZECTRIX_FONT` → `~/Library/Fonts/Zfull.ttf`（点阵，8-24px 像素级锐利，最推荐）→ PingFang → 黑体 → Noto CJK。小字号中文想要锯齿感就用点阵字体
- **图标**：`draw_icon()` 用两遍绘制（先描边色外扩、再填背景色）得到无内线的粗轮廓，云体还能自然遮挡背后的太阳；▲▼ 等多字节符号在点阵字体里小字号会缺字形，一律用代码画
- **文字一律默认字重**，不加粗不描边（加粗在 1-bit 屏上会糊成一团）
- **右栏图标+温度整体居中**：先 `d.textlength()` 量温度实际宽度，再以右栏中线为基准算组合起点，晴天图标光芒外扩，占位宽度要单独加宽
- 印章旋转用 `fillcolor=255` 避免黑角；反白场景印章要用 `img.paste(tcol, box, mask)` 按框内色粘贴

## 四、定时推送

设备是**拉取式**刷新，API 返回 `code:0` 即成功，屏幕会在下次轮询时更新。文案按时段变化，建议配自动化每天 10:00 推一次；想让周日 19:00 后显示「明天周一。」、周五 16:00 后出现「退朝」章，需再补一条 19:00 的推送。

## 五、文件说明

| 文件 | 说明 |
|------|------|
| `scripts/init.py` | 初始化向导：收集 Key/设备/地区，地理编码，写配置 |
| `scripts/zectrix_friday_push.py` | 渲染 + 推送主脚本 |
| `scripts/dev_render_sample.py` | 生成文档示例图（指定星期/时段/天气，不推送） |
| `scripts/friday_phrases.json` | 9×65 条文案池，可直接编辑扩充 |
| `assets/preview.png` | 效果预览图 |
| `assets/sample-friday.png` | 周五傍晚示例（黑底反白 + 退朝印章） |

天气数据来自 [Open-Meteo](https://open-meteo.com)（免费、无需注册 Key），紫外线取当日 `uv_index_max`。
