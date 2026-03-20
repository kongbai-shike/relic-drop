# Warframe Relic EV Tool

一个带 GUI/CLI 的 Warframe 遗物 EV 小工具。价格来源于 warframe.market，遗物掉落来源于 Wiki。

## 功能

- 查询流程：先读本地 `relics.json`，找不到目标遗物时自动从 Wiki 拉取该遗物并回写本地
- 支持批量查询：可一次输入多个遗物，逐条计算并汇总展示
- 批量结果可排序：按给定列表顺序 / 按 EV 从高到低 / 按 EV 从低到高
- 批量结果列包含：遗物名、常见、稀有(2项)、传说(1项)、EV
- 批量结果“说明”列支持状态标识：`🟡 入库` / `🔵 出库` / `⚪ 未知`
- 支持截图识别：从游戏截图中自动识别遗物名称，自动填入批量输入并发起批量查询
- 支持剪贴板识图：复制图片后可直接从剪贴板识别遗物名称
- 设置里可调 `批量并发`（1~32，默认 8）
- 内置 10 分钟短时内存价格缓存，重复查询可更快
- Validates each relic has exactly `3 common + 2 uncommon + 1 rare`
- Supports all refinement levels: `intact`, `exceptional`, `flawless`, `radiant`
- Uses `EV = sum(probability * lowest_sell_price)`
- Robust API handling (`404`, empty orders, network issues): item shows `N/A`, script keeps running
- Built-in fallback: `Forma Blueprint` defaults to `1p` when API price is unavailable
- Debug mode (`--debug`) prints endpoint detection, cache behavior, request status, and item mapping details
- GUI 支持「时代 + 核桃代号」双下拉：`古/前/中/后纪/安魂/赤毒` + 对应代号
- 仍支持直接输入，输入时会弹出候选提示（如 `中纪A9` / `Meso A9`）

## Requirements

- Python 3.8+
- `requests`
- `rapidocr-onnxruntime`
- `pillow`

Install dependency:

```powershell
python -m pip install -r requirements.txt
```

## 使用

### GUI (recommended)

```powershell
python main.py
```

or

```powershell
python relic_gui.py
```

在 GUI 中可以：

1. 左边选时代，右边选核桃代号；或
2. 直接输入遗物名（例如 `中纪A9`）

然后点击 `查询`。

批量查询：

1. 在「批量输入」文本框输入多个遗物（每行一个，或用 `,`/`，`/`;`/`；` 分隔）
2. 选择排序方式
3. 点击 `批量查询`，下方表格会逐条展示结果

截图识别：

1. 点击 `识图导入`
2. 选择包含遗物卡片的截图（png/jpg 等）
3. 程序会先把识别结果填入批量输入框（可手动编辑）
4. 确认后点击 `批量查询`

剪贴板识图：

1. 先将截图复制到系统剪贴板（例如微信截图、QQ截图、PrintScreen 后粘贴来源）
2. 在批量页点击 `识别剪贴板`
3. 程序会将识别到的遗物及数量填入批量输入框

说明：

- 识图结果支持数量后缀（例如 `Meso A6 x3`）
- 批量输入框也支持手动填写 `xN` / `*N` 格式
- OCR 识别包含置信度过滤，可在 `设置` 中调整 `OCR阈值`（0~1）
- 可在 `设置` 中调整 `批量并发`（1~32），网络好时适当增大可提升批量速度
- 若剪贴板不是图片，程序会提示并保持当前输入不变

CLI 示例：

```powershell
python relic_ev.py "Lith A1" -r radiant --status any
```

全量爬取并更新本地遗物库（`relics.json`）：

```powershell
python relic_ev.py --refresh-only --debug
```

带调试日志：

```powershell
python relic_ev.py "Lith A1" -r radiant --status any --debug
```

## 主要参数

- `relic` (positional): Relic name, for example `"Lith A1"`
- `--refinement`, `-r`: `intact|exceptional|flawless|radiant` (default: `intact`)
- `--static-relic-db`: 本地遗物库路径（默认 `relics.json`）
- `--refresh-relic-db`: 强制全量从 Wiki 刷新本地 `relics.json`（较慢）
- `--status`: seller status filter for prices
  - `ingame` (default)
  - `online` (`online` + `ingame`)
  - `any`
- `--cache-path`: local items index cache path (default: `.cache_wfm/items_index_pc_en.json`)
- `--cache-ttl-hours`: cache TTL in hours (default: `24`)
- `--timeout`: HTTP timeout in seconds (default: `12`)
- `--crossplay`: `true|false` (default: `true`), maps to WFM `Crossplay` request header
- `--debug`: print API and parsing debug information

## 遗物与价格数据来源

遗物掉落：

1. 优先本地 `relics.json`
2. 本地无该遗物时，先尝试官方 `relicRewards` 页面解析
3. 官方源未命中时，请求 Wiki 该遗物页面并解析掉落
4. 自动将新遗物写回 `relics.json`

价格查询：

1. First tries search endpoint: `GET /v2/items/search/{query}` (with legacy search fallback)
2. Parses multiple possible response shapes to resolve `slug/url_name`
3. If search fails, falls back to local cached item index (`.cache_wfm/items_index_pc_en.json`)
4. Uses `GET /v2/orders/item/{slug}` to get sell orders (with legacy fallback if needed)

## Output

The script prints one row per drop:

- Rarity
- Probability
- Lowest sell price (platinum)
- EV contribution
- Item name

And final:

- `Expected value (EV): ... platinum`

## Troubleshooting

### 1) Many `N/A` prices

Possible causes:

- Market endpoint temporarily unavailable
- Item not found in cached/detected index
- No sell orders matching selected `--status`

Try:

```powershell
python relic_ev.py "Lith A1" -r radiant --static-relic-db relics.json --status any --debug
```

Also try deleting cache so the index is rebuilt:

```powershell
Remove-Item ".cache_wfm\items_index_pc_en.json" -ErrorAction SilentlyContinue
```

### 2) Endpoint 404 / API shape changed

Use `--debug` to inspect which endpoint probe succeeded or failed. The tool is v2-first and includes fallback behavior for compatibility.

### 3) Relic format errors

If you see validation errors, check `relics.json`:

- Each relic must contain exactly 6 drops
- Rarity counts must be `3 common`, `2 uncommon`, `1 rare`

