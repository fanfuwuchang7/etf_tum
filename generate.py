#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多基金 QDII / ETF 低位网格监控
用法：在 FUNDS 列表里按 ("代码", "名称") 格式添加即可，其余全自动
     ETF 代码带交易所前缀：sh510300 / sz159915（脚本自动去掉前缀取数据）
"""

import requests
import re
import json
import os
import unicodedata
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(BASE_DIR, "docs", "index.html")

# ================== 你只改这里 ==================
# 格式：("代码", "名称")
#   场外基金：直接写 6 位数字代码
#   ETF：    代码前加交易所前缀 sh（沪市）/ sz（深市）
#
# 种子池来源：天天基金「开放式 QDII」全量榜单，截至 2026-10-25 共 220 只份额，
#   同一产品的 A/C/E 份额已合并，优先保留 C 类（129 只基金里 90 只有 C 类）。
#   没有 C 类的优先用 D 类（收费结构等同 C，如国泰大宗商品 025162）；
#   既没有 C 也没有 D 的，只能保留 A 类（如 050020 博时抗通胀、000043 嘉实美国成长等）。
#   债券/美元债那一段净值几乎不动，做网格没意义，不需要可整段删掉。
FUNDS = [
    # ---------- 自选 ----------
    ("007844", "华宝标普油气上游股票人民币C"),
    ("017437", "华宝纳斯达克精选股票发起式(QDII)C"),
    ("016702", "银华海外数字经济量化选股混合发起式(QDII)C"),
    ("015202", "汇添富全球移动互联混合(QDII)人民币C"),
    ("018147", "建信新兴市场混合(QDII)C"),
    ("161128", "易方达标普500"),
    ("012806", "广发道琼斯石油"),

    # ---------- 商品 / 黄金 / 能源 / 抗通胀（6只） ----------
    ("019578", "摩根全球天然资源混合(QDII)C"),
    ("020969", "中信保诚全球商品(QDII)C"),
    ("021694", "银华抗通胀主题(QDII-FOF-LOF)C"),
    ("027784", "诺安全球黄金(QDII-FOF)C"),
    ("050020", "博时抗通胀增强回报"),
    ("025162", "国泰大宗商品(QDII-LOF)D"),

    # ---------- 美股 / 纳斯达克 / 标普（2只，华宝纳指已在自选） ----------
    ("000043", "嘉实美国成长股票人民币"),
    ("206011", "鹏华美国房地产(QDII)"),

    # ---------- 医药 / 医疗 / 健康（12只） ----------
    ("004877", "汇添富全球医疗混合(QDII)人民币"),
    ("018156", "创金合信全球医药生物股票发起(QDII)C"),
    ("019035", "易方达全球医药行业混合发起式(QDII)C(人民币)"),
    ("019416", "南方港股医药行业混合发起(QDII)C"),
    ("019573", "摩根中国生物医药混合(QDII)C"),
    ("023907", "富国全球健康生活主题混合(QDII)人民币C"),
    ("025071", "东方红医疗创新混合(QDII)C"),
    ("025175", "长城港股医疗保健精选混合发起(QDII)C"),
    ("025655", "富国医药精选混合(QDII)C"),
    ("026260", "银华医疗创新混合(QDII)C"),
    ("026358", "平安港股医疗优选股票(QDII)C"),
    ("027380", "中欧港股医药混合发起(QDII)C"),

    # ---------- 债券 / 美元债（23只，网格意义不大，可整段删除） ----------
    ("000103", "国泰境外高收益债(QDII)"),
    ("000290", "鹏华全球高收益债(QDII)"),
    ("001063", "华夏收益债券(QDII)C"),
    ("002393", "华安全球美元收益债C"),
    ("002401", "南方亚洲美元收益债券(QDII)C(人民币)"),
    ("002429", "华安全球美元票息债C"),
    ("002880", "华夏大中华信用债C"),
    ("003387", "工银全球美元债C"),
    ("003972", "国富美元债一年持有期债券(QDII)人民币"),
    ("004420", "汇添富美元债债券(QDII)人民币C"),
    ("004998", "长信全球债券人民币"),
    ("007205", "银华美元债精选债券(QDII)C"),
    ("007361", "易方达中短期美元债(QDII)C人民币"),
    ("008096", "中银亚太精选债券(QDII)人民币C"),
    ("008320", "鹏华全球中短债(QDII)人民币C"),
    ("008752", "大成全球美元债(QDII)C人民币"),
    ("013508", "广发亚太中高收益债(QDII)C"),
    ("019480", "博时亚洲票息收益债券C人民币"),
    ("019518", "富国全球债券(QDII)人民币C"),
    ("019709", "富国亚洲收益债券(QDII)人民币C"),
    ("019893", "中银美元债债券(QDII)人民币C"),
    ("020571", "融通中国概念债券(QDII)C"),
    ("501300", "海富通全球收益债券人民币"),

    # ---------- 区域：日本 / 印度 / 越南 / 欧洲 / 亚太（14只） ----------
    ("006105", "宏利印度股票(QDII)A"),
    ("008764", "天弘越南市场股票发起(QDII)C"),
    ("019449", "摩根日本精选股票(QDII)C"),
    ("019450", "摩根欧洲动力策略股票(QDII)C"),
    ("019641", "摩根亚太优势混合(QDII)C"),
    ("021662", "国富亚洲机会股票(QDII)C"),
    ("027170", "交银环球精选混合(QDII)C"),
    ("027794", "诺安全球收益不动产(QDII)C"),
    ("050015", "博时大中华亚太精选"),
    ("070031", "嘉实全球房地产(QDII)"),
    ("080006", "长盛环球行业混合(QDII)A"),
    ("118001", "易方达亚洲精选股票"),
    ("164824", "工银印度基金人民币"),
    ("460010", "华泰柏瑞亚洲领导企业混合"),

    # ---------- 港股 / 中概 / 大中华（26只） ----------
    ("001691", "南方香港成长灵活配置混合"),
    ("002230", "华夏大中华混合(QDII)"),
    ("002379", "工银香港中小盘人民币"),
    ("003243", "摩根中国世纪混合(QDII)人民币"),
    ("007455", "富国蓝筹精选股票(QDII)人民币"),
    ("011584", "大成港股精选混合(QDII)C"),
    ("012209", "华夏港股前沿经济混合(QDII)C"),
    ("012380", "创金合信港股互联网3个月持有期混合(QDII)C"),
    ("012585", "南方中国新兴经济9个月持有期混合(QDII)C"),
    ("013364", "大成中国优势混合(QDII)C"),
    ("015885", "中欧港股数字经济混合发起(QDII)C"),
    ("016742", "华安大中华升级股票(QDII)C"),
    ("024846", "富国中国中小盘混合(QDII)人民币C"),
    ("025589", "光大阳光香港精选混合(QDII)C人民币"),
    ("026247", "汇丰晋信港股精选股票(QDII)人民币C"),
    ("026292", "中欧港股消费混合发起(QDII)C"),
    ("026704", "长城港股价值优选股票(QDII)C"),
    ("027451", "交银港股消费混合(QDII)C"),
    ("028042", "宏利港股数字经济混合发起(QDII)C"),
    ("029177", "国投瑞银中国价值发现股票(QDII-LOF)C"),
    ("040018", "华安香港精选股票(QDII)"),
    ("070012", "嘉实海外中国股票混合"),
    ("160125", "南方香港优选股票"),
    ("161229", "国投中国价值LOF"),
    ("241001", "华宝海外中国成长混合"),
    ("519601", "海富通中国海外混合"),

    # ---------- 其他全球主题（45只） ----------
    ("000041", "华夏全球股票(QDII)(人民币)"),
    ("000342", "嘉实新兴市场A1(QDII)"),
    ("000988", "嘉实全球互联网股票人民币"),
    ("002891", "华夏移动互联灵活配置混合(QDII)"),
    ("005534", "华夏新时代混合人民币(QDII)"),
    ("006309", "汇添富全球消费混合(QDII)人民币C"),
    ("006448", "华夏海外聚享混合发起式(QDII-FOF)C人民币"),
    ("008254", "华宝致远混合(QDII)C"),
    ("009108", "富国红利精选混合(QDII)人民币"),
    ("012062", "富国全球消费精选混合(QDII)人民币C"),
    ("012536", "万家全球成长一年持有期混合(QDII)C"),
    ("012922", "易方达全球成长精选混合(QDII)人民币C"),
    ("013328", "嘉实全球价值股票(QDII)人民币"),
    ("014002", "浦银全球智能科技(QDII)C"),
    ("014127", "融通核心价值混合(QDII)C"),
    ("015205", "银华全球新能源车量化优选股票(QDII)C"),
    ("016202", "汇添富全球汽车产业升级混合(QDII)人民币C"),
    ("016665", "天弘全球高端制造混合(QDII)C"),
    ("016823", "天弘全球新能源汽车股票(QDII-LOF)C"),
    ("017072", "申万菱信全球新能源股票型发起式(QDII)C"),
    ("017145", "华宝海外新能源汽车股票发起式(QDII)C"),
    ("017204", "华宝海外科技股票(QDII-LOF)C"),
    ("017431", "嘉实全球创新龙头股票(QDII)人民币C"),
    ("017731", "嘉实全球产业升级股票发起式(QDII)C"),
    ("018036", "长城全球新能源车股票发起式(QDII)C"),
    ("018230", "易方达全球优质企业混合(QDII)C(人民币份额)"),
    ("019075", "嘉实全球产业精选混合发起式(QDII)人民币"),
    ("019156", "易方达全球配置混合(QDII)C(人民币)"),
    ("019231", "广发全球稳健配置混合(QDII)人民币C"),
    ("019512", "摩根全球多元配置(QDII-FOF)人民币C"),
    ("020512", "摩根海外稳健配置混合(QDII-FOF)人民币C"),
    ("020957", "中银全球策略(QDII-FOF)C"),
    ("021277", "广发全球精选股票(QDII)人民币C"),
    ("021842", "国富全球科技互联混合(QDII)人民币C"),
    ("022184", "富国全球科技互联网股票(QDII)C"),
    ("023559", "招商普盛全球配置(QDII)人民币C"),
    ("023591", "南方全球精选配置股票(QDII-FOF)C(人民币)"),
    ("024239", "华夏全球科技先锋混合(QDII)C"),
    ("025403", "工银新经济混合(QDII)人民币C"),
    ("027206", "广发优势企业混合(QDII)C"),
    ("110011", "易方达优质精选混合(QDII)"),
    ("378006", "摩根全球新兴市场混合(QDII)"),
    ("486002", "工银全球精选股票(QDII)"),
]
PLAN_TOTAL_MONEY = 1000      # 每只基金的分批投入金额（买入计划用）
SHOW_DETAIL = False           # 终端是否打印每只基金的网格详情（标的多了会很刷屏）
WRITE_HTML = True             # 是否生成看板 docs/index.html

# ---------------- 邮件通知配置 ----------------
# 跑完数据后，把看板（纯文本摘要正文 + 完整交互页面附件）发到邮箱。
# 凭据建议用「环境变量」，别把授权码明文写进仓库：
#   MAIL_HOST  SMTP 服务器，如 smtp.qq.com / smtp.163.com / smtp.gmail.com
#   MAIL_PORT  通常 465(SSL) 或 587(STARTTLS)
#   MAIL_USER  发件邮箱
#   MAIL_PASS  授权码（不是登录密码）
#   MAIL_TO   收件邮箱，多个用英文逗号分隔
# 本地没配环境变量又想直接写死，可填进下面默认值（注意不要提交授权码）。
SEND_EMAIL = True
MAIL = {
    "host": os.environ.get("MAIL_HOST", "smtp.qq.com"),
    "port": int(os.environ.get("MAIL_PORT", "465") or 0),
    "user": os.environ.get("MAIL_USER", "783109755@qq.com"),
    "pass": os.environ.get("MAIL_PASS", "sahjbwruqwedbedj"),
    "to":   os.environ.get("MAIL_TO", "809080777@qq.com,1279885368@qq.com,120957262@qq.com,1013562640@qq.com"),
}
# ==============================================

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
}


def split_code(code):
    """sh510300 -> ("sh", "510300")；017437 -> ("", "017437")"""
    m = re.fullmatch(r"(sh|sz)?(\d{6})", code.lower())
    if not m:
        raise ValueError(f"无法识别的代码：{code}")
    return m.group(1) or "", m.group(2)


def w(s):
    """字符串的终端显示宽度（中文/全角按 2 计）"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in str(s))


def pad(s, width, align="<"):
    """按显示宽度补空格，保证中文列对齐"""
    s = str(s)
    fill = " " * max(0, width - w(s))
    return s + fill if align == "<" else fill + s

# 买入分档：分位 -> (标签, 仓位占比)
BUY_TIERS = [
    ("20%", "🟢🟢 极度低估", 0.40),
    ("40%", "🟢 低估",      0.30),
    ("60%", "🟡 中性",      0.15),
    ("80%", "🟠 偏高",      0.10),
]


# ---------------- 数据接口 ----------------
def _pingzhong(code):
    url = f"http://fund.eastmoney.com/pingzhongdata/{code}.js"
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.encoding = "utf-8"
    m = re.search(r"Data_netWorthTrend\s*=\s*(\[.*?\]);", r.text, re.DOTALL)
    if not m:
        raise RuntimeError("无净值序列")
    arr = json.loads(m.group(1))
    out = []
    for it in arr:
        d = datetime.fromtimestamp(it["x"] / 1000).strftime("%Y-%m-%d")
        out.append((d, float(it["y"])))
    return out


def _lsjz(code, days=365):
    end = datetime.today()
    start = end - timedelta(days=int(days * 1.5))
    out = []
    for page in range(1, 50):
        url = "https://api.fund.eastmoney.com/f10/lsjz"
        params = {
            "fundCode": code, "pageIndex": page, "pageSize": 40,
            "startDate": start.strftime("%Y-%m-%d"),
            "endDate": end.strftime("%Y-%m-%d"),
        }
        j = requests.get(url, params=params, headers=HEADERS, timeout=10).json()
        lst = j.get("Data", {}).get("LSJZList", [])
        if not lst:
            break
        for row in lst:
            d, nav = row.get("FSRQ"), row.get("DWJZ")
            if d and nav not in (None, ""):
                out.append((d, float(nav)))
        if len(lst) < 40:
            break
    return sorted(set(out))


def load_series(code):
    try:
        rows = _pingzhong(code)
        if rows:
            return rows, "pingzhong"
    except Exception:
        pass
    return _lsjz(code), "lsjz"


# ---------------- 策略计算 ----------------
def analyze(series):
    cutoff = (datetime.today() - timedelta(days=365)).strftime("%Y-%m-%d")
    recent = [(d, v) for d, v in series if d >= cutoff] or series[-250:]
    vals = [v for _, v in recent]
    low, high = min(vals), max(vals)
    cur = vals[-1]

    if high == low:
        lin = 50.0
    else:
        lin = (cur - low) / (high - low) * 100
    below = sum(1 for v in vals if v <= cur) / len(vals) * 100

    plan = {}
    for k, _, _ in BUY_TIERS:
        f = int(k[:-1]) / 100
        plan[k] = low + (high - low) * f

    ret1y = (cur / vals[0] - 1) * 100
    from_low = (cur / low - 1) * 100

    if lin < 20:
        signal = "🟢🟢 极度低估"
    elif lin < 40:
        signal = "🟢 低估"
    elif lin < 60:
        signal = "🟡 中性"
    elif lin < 80:
        signal = "🟠 偏高"
    else:
        signal = "🔴 高位"

    return {
        "nav": cur, "low": low, "high": high,
        "lin": lin, "rank": below, "signal": signal,
        "ret1y": ret1y, "from_low": from_low,
        "plan": plan, "days": len(recent),
        "low_date": recent[vals.index(low)][0],
        "high_date": recent[vals.index(high)][0],
    }


# ---------------- 分类（看板筛选用） ----------------
CATEGORIES = [
    ("商品 / 黄金 / 能源", r"黄金|商品|石油|油气|资源|通胀"),
    ("美股 / 纳斯达克 / 标普", r"纳斯达克|标普|美国"),
    ("医药 / 医疗", r"医疗|医药|生物|健康"),
    ("债券 / 美元债", r"债"),
    ("区域市场", r"环球|日本|印度|越南|欧洲|亚太|亚洲|房地产|不动产"),
    ("港股 / 中概", r"港股|香港|大中华|中国|蓝筹|海外中国|新兴经济"),
]


def categorize(name):
    for c, pat in CATEGORIES:
        if re.search(pat, name):
            return c
    return "其他全球主题"


# ---------------- 看板渲染 ----------------
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QDII / 海外基金 低位网格监控</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1" integrity="sha384-jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ" crossorigin="anonymous"></script>
<style>
:root {
    --bg-primary: #f4f6f9;
    --bg-card: #ffffff;
    --bg-header: #101a2e;
    --text-primary: #212529;
    --text-secondary: #6c757d;
    --text-on-dark: #ffffff;
    --positive: #dc3545;
    --negative: #198754;
    --gap: 16px;
    --radius: 10px;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    line-height: 1.5;
}
.dashboard-container { max-width: 1440px; margin: 0 auto; padding: var(--gap); }
.dashboard-header {
    background: var(--bg-header); color: var(--text-on-dark);
    padding: 18px 22px; border-radius: var(--radius); margin-bottom: var(--gap);
    display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 14px;
}
.dashboard-header h1 { font-size: 20px; font-weight: 600; }
.dashboard-header .sub { font-size: 12px; color: rgba(255,255,255,0.65); margin-top: 4px; }
.filters { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.filter-group { display: flex; align-items: center; gap: 6px; font-size: 12px; color: rgba(255,255,255,0.7); }
.filter-group select, .filter-group input[type="search"] {
    padding: 6px 10px; border: 1px solid rgba(255,255,255,0.2); border-radius: 6px;
    background: rgba(255,255,255,0.1); color: var(--text-on-dark); font-size: 13px;
}
.filter-group input[type="search"] { width: 160px; }
.filter-group select option { background: var(--bg-header); color: var(--text-on-dark); }
.filter-group input[type="checkbox"] { accent-color: #4dabf7; }
.kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: var(--gap); margin-bottom: var(--gap); }
.kpi-card {
    background: var(--bg-card); border-radius: var(--radius); padding: 16px 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}
.kpi-label { font-size: 12px; color: var(--text-secondary); letter-spacing: .5px; margin-bottom: 6px; }
.kpi-value { font-size: 26px; font-weight: 700; }
.kpi-sub { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }
.chart-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: var(--gap); margin-bottom: var(--gap); }
.chart-container { background: var(--bg-card); border-radius: var(--radius); padding: 16px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.chart-container h3 { font-size: 14px; font-weight: 600; margin-bottom: 12px; }
.chart-box { position: relative; height: 280px; }
.table-section { background: var(--bg-card); border-radius: var(--radius); padding: 16px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); overflow-x: auto; }
.table-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 10px; }
.table-head h3 { font-size: 14px; font-weight: 600; }
.table-head span { font-size: 12px; color: var(--text-secondary); }
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table thead th {
    text-align: left; padding: 9px 10px; border-bottom: 2px solid #dee2e6;
    color: var(--text-secondary); font-weight: 600; font-size: 12px;
    white-space: nowrap; cursor: pointer; user-select: none;
}
.data-table thead th:hover { color: var(--text-primary); background: #f8f9fa; }
.data-table tbody td { padding: 8px 10px; border-bottom: 1px solid #f1f3f5; white-space: nowrap; }
.data-table tbody tr:hover { background: #f8f9fa; }
.pos { color: var(--positive); }
.neg { color: var(--negative); }
.sig { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 12px; color: #fff; }
.muted { color: var(--text-secondary); }
.dashboard-footer { margin-top: var(--gap); font-size: 12px; color: var(--text-secondary); display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
@media (max-width: 768px) {
    .dashboard-header { flex-direction: column; align-items: flex-start; }
    .chart-row { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<div class="dashboard-container">
    <header class="dashboard-header">
        <div>
            <h1>QDII / 海外基金 低位网格监控</h1>
            <div class="sub">数据源：天天基金（近一年净值区间） | 更新于 __UPDATED__</div>
        </div>
        <div class="filters">
            <div class="filter-group">
                <label for="f-cat">分类</label>
                <select id="f-cat"><option value="all">全部</option></select>
            </div>
            <div class="filter-group">
                <label for="f-signal">信号</label>
                <select id="f-signal"><option value="all">全部</option></select>
            </div>
            <div class="filter-group">
                <input type="search" id="f-q" placeholder="搜索名称 / 代码">
            </div>
            <div class="filter-group">
                <label for="f-buy"><input type="checkbox" id="f-buy"> 只看可关注（分位 &lt; 60%）</label>
            </div>
        </div>
    </header>

    <section class="kpi-row" id="kpi-row"></section>

    <section class="chart-row">
        <div class="chart-container">
            <h3>信号分布</h3>
            <div class="chart-box"><canvas id="chart-signal"></canvas></div>
        </div>
        <div class="chart-container">
            <h3>距一年高点跌幅 TOP 12（跌得越多越便宜）</h3>
            <div class="chart-box"><canvas id="chart-top"></canvas></div>
        </div>
        <div class="chart-container">
            <h3>线性分位 × 距低点</h3>
            <div class="chart-box"><canvas id="chart-scatter"></canvas></div>
        </div>
    </section>

    <section class="table-section">
        <div class="table-head">
            <h3>标的一览（点击表头排序）</h3>
            <span id="row-count"></span>
        </div>
        <div id="table-container"></div>
    </section>

    <footer class="dashboard-footer">
        <span>生成时间：__UPDATED__</span>
        <span>线性分位 = 当前净值在近一年高/低区间中的相对位置，越低越接近底部；触发买入价为下一档网格线价格。仅供参考，不构成投资建议。</span>
    </footer>
</div>

<script>
const DATA = __DATA__;
const UPDATED = "__UPDATED__";
const SIG_COLOR = {
    "🟢🟢 极度低估": "#198754",
    "🟢 低估": "#43a047",
    "🟡 中性": "#f59f00",
    "🟠 偏高": "#e8590c",
    "🔴 高位": "#dc3545"
};
const PALETTE = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3", "#937860", "#4E79A7"];

const pct = v => v.toFixed(1) + "%";
const signPct = v => (v >= 0 ? "+" : "") + v.toFixed(2) + "%";

const COLUMNS = [
    { field: "name", label: "基金" },
    { field: "cat", label: "分类" },
    { field: "code", label: "代码" },
    { field: "nav", label: "当前净值", align: "right", fmt: v => v.toFixed(4) },
    { field: "lin", label: "线性分位", align: "right", fmt: pct, cls: v => v < 40 ? "neg" : (v >= 80 ? "pos" : "") },
    { field: "rank", label: "排名分位", align: "right", fmt: pct },
    { field: "signal", label: "信号", fmt: (v, row) => '<span class="sig" style="background:' + (SIG_COLOR[row.signal] || "#6c757d") + '">' + v + "</span>" },
    { field: "ret1y", label: "1年涨跌", align: "right", fmt: signPct, cls: v => v >= 0 ? "pos" : "neg" },
    { field: "from_low", label: "距低点", align: "right", fmt: signPct, cls: v => v >= 0 ? "pos" : "neg" },
    { field: "range", label: "近一年区间", sort: r => r.low, fmt: (v, r) => r.low.toFixed(4) + " ~ " + r.high.toFixed(4) },
    { field: "trigger", label: "触发买入价", align: "right", sort: r => r.trigger == null ? 1e9 : r.trigger, fmt: v => v == null ? '<span class="muted">观望</span>' : v.toFixed(4) }
];

class Dashboard {
    constructor(data) {
        this.raw = data;
        this.filtered = data.slice();
        this.sortField = "lin";
        this.sortDir = "asc";
        this.charts = {};
        this.init();
    }

    init() {
        this.setupFilters();
        this.renderKPIs();
        this.renderCharts();
        this.renderTable();

        const help = (id) => { document.getElementById(id).addEventListener("change", () => this.applyFilters()); document.getElementById(id).addEventListener("input", () => this.applyFilters()); };
        help("f-cat"); help("f-signal"); help("f-q"); help("f-buy");
    }

    setupFilters() {
        const cats = [...new Set(this.raw.map(d => d.cat))].sort();
        const sigs = [...new Set(this.raw.map(d => d.signal))];
        const fill = (id, values) => {
            const el = document.getElementById(id);
            values.forEach(v => {
                const opt = document.createElement("option");
                opt.value = v; opt.textContent = v;
                el.appendChild(opt);
            });
        };
        fill("f-cat", cats);
        fill("f-signal", sigs);
    }

    applyFilters() {
        const cat = document.getElementById("f-cat").value;
        const sig = document.getElementById("f-signal").value;
        const q = document.getElementById("f-q").value.trim().toLowerCase();
        const buyOnly = document.getElementById("f-buy").checked;

        this.filtered = this.raw.filter(d => {
            if (cat !== "all" && d.cat !== cat) return false;
            if (sig !== "all" && d.signal !== sig) return false;
            if (buyOnly && !(d.lin < 60)) return false;
            if (q && !(d.name.toLowerCase().includes(q) || d.code.includes(q))) return false;
            return true;
        });
        this.renderKPIs();
        this.updateCharts();
        this.renderTable();
    }

    renderKPIs() {
        const d = this.filtered;
        const nLow = d.filter(x => x.lin < 40).length;
        const nBuy = d.filter(x => x.lin < 60).length;
        const nHigh = d.filter(x => x.lin >= 80).length;
        const avg = d.length ? d.reduce((s, x) => s + x.lin, 0) / d.length : 0;
        const maxR = d.reduce((a, x) => (a === null || x.lin > a.lin ? x : a), null);
        const minR = d.reduce((a, x) => (a === null || x.lin < a.lin ? x : a), null);
        const card = (label, value, sub, cls) =>
            '<div class="kpi-card"><div class="kpi-label">' + label + '</div><div class="kpi-value ' + (cls || "") + '">' + value + '</div><div class="kpi-sub">' + sub + '</div></div>';

        document.getElementById("kpi-row").innerHTML =
            card("监控标的", d.length, "筛选后数量 / 全池 " + this.raw.length) +
            card("低估区（&lt;40%）", nLow,
                minR ? "最低 " + minR.lin.toFixed(1) + "%：" + minR.name.slice(0, 12) : "无数据",
                nLow ? "neg" : "") +
            card("可关注（&lt;60%）", nBuy,
                "占比 " + (d.length ? (nBuy / d.length * 100).toFixed(0) : 0) + "%，含中性区可小仓") +
            card("高位区（≥80%）", nHigh,
                nHigh ? "建议观望不追高" : (maxR ? "暂无，最高 " + maxR.lin.toFixed(1) + "%：" + maxR.name.slice(0, 10) : "无数据"),
                nHigh ? "pos" : "") +
            card("平均线性分位", avg.toFixed(1) + "%", "越低整体越便宜");
    }

    renderCharts() {
        Chart.defaults.animation = false;
        Chart.defaults.font.size = 11;

        this.charts.signal = new Chart(document.getElementById("chart-signal"), {
            type: "doughnut",
            data: { labels: [], datasets: [{ data: [], backgroundColor: [], borderColor: "#fff", borderWidth: 2 }] },
            options: {
                responsive: true, maintainAspectRatio: false, cutout: "58%",
                plugins: {
                    legend: { position: "right", labels: { usePointStyle: true, padding: 12 } },
                    tooltip: {
                        callbacks: {
                            label: c => {
                                const total = c.dataset.data.reduce((a, b) => a + b, 0);
                                return c.label + ": " + c.parsed + " 只 (" + (c.parsed / total * 100).toFixed(1) + "%)";
                            }
                        }
                    }
                }
            }
        });

        this.charts.top = new Chart(document.getElementById("chart-top"), {
            type: "bar",
            data: { labels: [], datasets: [{ data: [], backgroundColor: [], borderRadius: 4 }] },
            options: {
                responsive: true, maintainAspectRatio: false, indexAxis: "y",
                plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => "距高点 " + c.parsed.x.toFixed(1) + "%（越短/越接近右端跌幅越小）" } } },
                scales: {
                    x: { beginAtZero: false, max: 0, title: { display: true, text: "距一年高点 %" } },
                    y: { ticks: { autoSkip: false } }
                }
            }
        });

        this.charts.scatter = new Chart(document.getElementById("chart-scatter"), {
            type: "scatter",
            data: { datasets: [{ data: [], backgroundColor: [], pointRadius: 4 }] },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: c => {
                                const r = c.raw.row;
                                return r.name + " | 分位 " + r.lin.toFixed(1) + "% | 距低点 " + signPct(r.from_low) + " | 现价 " + r.nav.toFixed(4);
                            }
                        }
                    }
                },
                scales: {
                    x: { beginAtZero: true, max: 100, title: { display: true, text: "线性分位 %" } },
                    y: { title: { display: true, text: "距低点 %" } }
                }
            }
        });

        this.updateCharts();
    }

    updateCharts() {
        const d = this.filtered;
        const sigCount = {};
        d.forEach(x => { sigCount[x.signal] = (sigCount[x.signal] || 0) + 1; });
        const sig = this.charts.signal;
        sig.data.labels = Object.keys(sigCount);
        sig.data.datasets[0].data = Object.values(sigCount);
        sig.data.datasets[0].backgroundColor = Object.keys(sigCount).map(s => SIG_COLOR[s] || "#6c757d");
        sig.update("none");

        // 分位为 0 的标的会有很多并列（都处于一年新低），条形长度全为 0，
        // 所以这里改用「距一年高点跌幅」排序，永远能看出差别
        const top = d.map(r => ({ r: r, drop: (r.nav / r.high - 1) * 100 }))
            .sort((a, b) => a.drop - b.drop)
            .slice(0, 12);
        const bar = this.charts.top;
        bar.data.labels = top.map(x => x.r.name.length > 16 ? x.r.name.slice(0, 16) + "…" : x.r.name);
        bar.data.datasets[0].data = top.map(x => +x.drop.toFixed(1));
        bar.data.datasets[0].backgroundColor = top.map(x => SIG_COLOR[x.r.signal] || "#6c757d");
        bar.update("none");

        const sc = this.charts.scatter;
        sc.data.datasets[0].data = d.map(r => ({ x: +r.lin.toFixed(1), y: +r.from_low.toFixed(1), row: r }));
        sc.data.datasets[0].backgroundColor = d.map(r => (SIG_COLOR[r.signal] || "#6c757d") + "CC");
        sc.update("none");
    }

    sortedRows() {
        const col = COLUMNS.find(c => c.field === this.sortField) || COLUMNS[4];
        const val = r => (col.sort ? col.sort(r) : (r[col.field] == null ? "" : r[col.field]));
        return this.filtered.slice().sort((a, b) => {
            const va = val(a), vb = val(b);
            const cmp = va < vb ? -1 : (va > vb ? 1 : 0);
            return this.sortDir === "asc" ? cmp : -cmp;
        });
    }

    renderTable() {
        const rows = this.sortedRows();
        let html = '<table class="data-table"><thead><tr>';
        COLUMNS.forEach(c => {
            const arrow = this.sortField === c.field ? (this.sortDir === "asc" ? " ▲" : " ▼") : "";
            const al = c.align === "right" ? ' style="text-align:right"' : "";
            html += '<th onclick="dashboard.sortBy(\'' + c.field + '\')"' + al + '>' + c.label + arrow + '</th>';
        });
        html += "</tr></thead><tbody>";
        rows.forEach(r => {
            html += '<tr title="' + r.name + "（" + r.code + "） 网格：" +
                Object.keys(r.plan).map(k => k + "=" + r.plan[k].toFixed(4)).join("  ") +
                " | 低点 " + r.low_date + " 高点 " + r.high_date + '">';
            COLUMNS.forEach(c => {
                const raw = c.field === "range" ? "" : r[c.field];
                const txt = c.fmt ? c.fmt(raw, r) : raw;
                const cls = c.cls && c.field !== "signal" ? c.cls(r[c.field]) : "";
                const al = c.align === "right" ? ' style="text-align:right"' : "";
                html += '<td class="' + cls + '"' + al + ">" + txt + "</td>";
            });
            html += "</tr>";
        });
        html += "</tbody></table>";
        document.getElementById("table-container").innerHTML = html;
        document.getElementById("row-count").textContent = "共 " + rows.length + " 条（全池 " + this.raw.length + " 只）";
    }

    sortBy(field) {
        if (this.sortField === field) {
            this.sortDir = this.sortDir === "asc" ? "desc" : "asc";
        } else {
            this.sortField = field;
            this.sortDir = field === "name" || field === "cat" || field === "code" ? "asc" : "asc";
        }
        this.renderTable();
    }
}

const dashboard = new Dashboard(DATA);
</script>
</body>
</html>
"""


def html_payload(rows):
    out = []
    for r in rows:
        out.append({
            "code": r["code"],
            "name": r["name"],
            "cat": r["cat"],
            "nav": round(r["nav"], 4),
            "lin": round(r["lin"], 1),
            "rank": round(r["rank"], 1),
            "signal": r["signal"],
            "ret1y": round(r["ret1y"], 2),
            "from_low": round(r["from_low"], 2),
            "low": round(r["low"], 4),
            "high": round(r["high"], 4),
            "low_date": r["low_date"],
            "high_date": r["high_date"],
            "days": r["days"],
            "trigger": None if r["trigger"] is None else round(r["trigger"], 4),
            "plan": {k: round(v, 4) for k, v in r["plan"].items()},
        })
    return out


def write_html(rows):
    html = (HTML_TEMPLATE
            .replace("__DATA__", json.dumps(html_payload(rows), ensure_ascii=False))
            .replace("__UPDATED__", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[看板] 已生成 {OUT_FILE}（{len(rows)} 只标的）")


def _email_body(rows):
    """邮件正文：纯 HTML 摘要（邮件客户端不执行 JS，正文用表格而非图表）"""
    n = len(rows)
    n_low = len([r for r in rows if r["lin"] < 40])
    n_buy = len([r for r in rows if r["lin"] < 60])
    n_high = len([r for r in rows if r["lin"] >= 80])
    avg = sum(r["lin"] for r in rows) / n if n else 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    buy = [r for r in rows if r["lin"] < 60]
    buy.sort(key=lambda x: x["lin"])
    rows_html = ""
    for r in buy:
        key = "20%" if r["lin"] < 20 else "40%" if r["lin"] < 40 else "60%"
        rows_html += (
            f"<tr><td>{r['name']}</td><td>{r['code']}</td>"
            f"<td>{r['lin']:.0f}%</td><td>{r['nav']:.4f}</td>"
            f"<td>{r['trigger']:.4f}</td><td>{r['signal']}</td></tr>"
        )

    return f"""<div style="font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;color:#212529">
  <h2 style="margin:0 0 12px">QDII / 海外基金 低位网格监控 · {now}</h2>
  <p style="margin:4px 0">监控标的 <b>{n}</b> 只 ｜ 低估(&lt;40%) <b>{n_low}</b> 只 ｜
     可关注(&lt;60%) <b>{n_buy}</b> 只 ｜ 高位(≥80%) <b>{n_high}</b> 只 ｜ 平均分位 <b>{avg:.1f}%</b></p>
  <p style="margin:4px 0;color:#6c757d">完整交互看板（含图表）见附件 <b>qdii-dashboard.html</b>，下载后用浏览器打开。</p>
  <h3 style="margin:16px 0 8px">可关注买入（按分位从低到高，共 {len(buy)} 只）</h3>
  <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-size:13px;width:100%">
    <thead><tr style="background:#f4f6f9">
      <th align="left">基金</th><th align="left">代码</th><th align="right">线性分位</th>
      <th align="right">当前净值</th><th align="right">触发买入价</th><th align="left">信号</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
  <p style="margin-top:14px;color:#999;font-size:12px">
    线性分位 = 当前净值在近一年高/低区间的位置，越低越接近底部；触发买入价 = 下一档网格线价格。
    仅供参考，不构成投资建议。</p>
</div>"""


def send_email(rows):
    if not SEND_EMAIL:
        return
    if not (MAIL["host"] and MAIL["port"] and MAIL["user"] and MAIL["pass"] and MAIL["to"]):
        print("[邮件] 未配置 MAIL_* 环境变量，跳过发送")
        return
    try:
        import smtplib
        import ssl
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from email.mime.application import MIMEApplication

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        n_buy = len([r for r in rows if r["lin"] < 60])

        msg = MIMEMultipart("mixed")
        msg["Subject"] = f"QDII 网格看板 {now} · {n_buy} 只可关注"
        msg["From"] = MAIL["user"]
        msg["To"] = MAIL["to"]

        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText("QDII 网格看板已更新，详见附件或下方摘要。", "plain", "utf-8"))
        alt.attach(MIMEText(_email_body(rows), "html", "utf-8"))
        msg.attach(alt)

        with open(OUT_FILE, "rb") as f:
            att = MIMEApplication(f.read(), Name="qdii-dashboard.html")
        att.add_header("Content-Disposition", "attachment", filename="qdii-dashboard.html")
        msg.attach(att)

        if MAIL["port"] == 465:
            server = smtplib.SMTP_SSL(MAIL["host"], MAIL["port"], timeout=30)
        else:
            server = smtplib.SMTP(MAIL["host"], MAIL["port"], timeout=30)
            server.starttls(context=ssl.create_default_context())
        server.login(MAIL["user"], MAIL["pass"])
        server.sendmail(MAIL["user"], [x.strip() for x in MAIL["to"].split(",")], msg.as_string())
        server.quit()
        print(f"[邮件] 已发送至 {MAIL['to']}")
    except Exception as e:
        print(f"[邮件] 发送失败：{e}")


# ---------------- 主流程 ----------------
def main():
    rows = []
    for code, name in FUNDS:
        try:
            mkt, num = split_code(code.strip())
            series, src = load_series(num)
            r = analyze(series)
            key = "20%" if r["lin"] < 20 else "40%" if r["lin"] < 40 else "60%" if r["lin"] < 60 else None
            r.update({
                "code": mkt + num, "name": name, "src": src,
                "cat": categorize(name),
                "trigger": None if key is None else r["plan"][key],
            })
            rows.append(r)
            print(f"[OK] {name}({mkt + num}) 来源={src} 共{len(series)}条")
        except Exception as e:
            print(f"[失败] {name}({code}) {e}")

    if not rows:
        print("没有可用数据")
        return

    # ---------- 总览表 ----------
    line = "=" * 86
    print("\n" + line)
    print(pad("基金", 20) + pad("代码", 10) + pad("当前净值", 10, ">")
          + pad("线性", 7, ">") + pad("排名", 7, ">") + "  "
          + pad("信号", 14) + pad("1年涨跌", 9, ">") + pad("距低点", 9, ">"))
    print("-" * 86)
    for r in rows:
        print(pad(r["name"], 20) + pad(r["code"], 10)
              + pad(f"{r['nav']:.4f}", 10, ">")
              + pad(f"{r['lin']:.0f}%", 7, ">")
              + pad(f"{r['rank']:.0f}%", 7, ">") + "  "
              + pad(r["signal"], 14)
              + pad(f"{r['ret1y']:+.1f}%", 9, ">")
              + pad(f"{r['from_low']:+.1f}%", 9, ">"))
    print(line)

    # ---------- 买入信号（按分位从低到高） ----------
    buy = [r for r in rows if r["lin"] < 60]
    buy.sort(key=lambda x: x["lin"])
    if buy:
        print("\n📉 可关注买入（按分位从低到高）：")
        for r in buy:
            if r["lin"] >= 40:
                line_key = "60%"
            elif r["lin"] >= 20:
                line_key = "40%"
            else:
                line_key = "20%"
            print(f"   {pad(r['name'], 20)} 当前 {r['nav']:.4f} 分位 {r['lin']:.0f}%  "
                  f"→ 跌到 {r['plan'][line_key]:.4f}({line_key}分位) 触发买入")
    else:
        print("\n📈 当前所有基金均在偏高/高位区，建议观望，不追高。")

    # ---------- 每只详情 ----------
    if SHOW_DETAIL:
        for r in rows:
            print(f"\n{'—' * 18} {r['name']}({r['code']}) {'—' * 18}")
            print(f"  区间 {r['low']:.4f}({r['low_date']}) ~ {r['high']:.4f}({r['high_date']})"
                  f" | 当前 {r['nav']:.4f}")
            print(f"  线性分位 {r['lin']:.0f}% | 排名分位 {r['rank']:.0f}% | {r['signal']}")
            print(f"  网格线：", end="")
            print("  ".join(f"{k}={r['plan'][k]:.4f}" for k, _, _ in BUY_TIERS))
            for k, label, frac in BUY_TIERS:
                print(f"    跌到 {r['plan'][k]:.4f}（{k}） {label} -> 投入 {PLAN_TOTAL_MONEY * frac:,.0f}元")

    # ---------- 今日一句 ----------
    n_low = len([r for r in rows if r["lin"] < 40])
    n_buy = len(buy)
    print("\n💡 今日策略：", end="")
    if n_buy == 0:
        print("全线偏高，管住手、不加仓，等回调。")
    elif n_low == 0:
        print(f"{n_buy} 只处于中性区，可小仓试水，未到重仓时机。")
    else:
        print(f"{n_low} 只处于低估/极度低估区，优先按网格分批买入。")

    # ---------- 生成看板 ----------
    if WRITE_HTML:
        write_html(rows)

    # ---------- 邮件通知 ----------
    send_email(rows)


if __name__ == "__main__":
    main()
