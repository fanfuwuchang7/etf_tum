#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETF 长周期双动量策略 v2 —— 单文件版（数据获取 + 回测 + HTML 看板 + 邮件通知）

依赖：
  pip install akshare>=1.12 pandas>=1.5 numpy>=1.23
  标准库：argparse json os pickle collections datetime time

v2 变更：
  - 标的池扩充至 24 只，新增煤炭ETF(515220.SH)、汇添富油气资源ETF(159309.SZ)、
    能源化工ETF(159981.SZ)、钢铁ETF(515210.SH) 等周期/能源品种
  - 新增「分类上限」机制：同一大类最多持仓 MAX_PER_CAT 只，避免仓位被同类占满
  - 新增分类映射 ETF_CATEGORY，用于分散度检查与看板分类饼图
  - 回测输出新增「分类分散度」统计，直观反映仓位集中度

策略原理（长周期双动量）：
  - 标的动量：对池内每只 ETF 计算中长期动量（如近 MOMENTUM_WINDOW 日收益），
    动量越高越强势。
  - 风险过滤（大盘动量）：用宽基指数的长周期均线(MARKET_MA)与动量(MARKET_MOMENTUM)
    判断市场状态——大盘在长周期均线之上且动量为正才允许持基；否则整体切现金空仓。
  - 选股与持仓：过滤通过后按动量排序取前 TOP_N 只等权持有；「同类上限」保证每类
    最多贡献 MAX_PER_CAT 只（默认 1），避免半导体/芯片/科创芯片等同质 ETF 扎堆。
  - 定期(REBALANCE_FREQ)检查，触发换仓时整体再平衡。USE_CASH=False 时退化成始终满仓选最强。

邮件通知（QQ邮箱 SMTP，已内联配置）：
  - 发件/收件/授权码直接写在文件内 EMAIL_SENDER / EMAIL_AUTH_CODE / EMAIL_RECEIVERS，
    改这几行即可，无需 .env。授权码必须绑定发件 QQ 号，否则登录被拒(SMTPServerDisconnected)。
  - EMAIL_ENABLED=True 即开启；运行时 --email 仅调仓时发信，--force-email 强制测试。
  - ⚠ 授权码已写进代码，推到公开仓库会泄露，请保持仓库私有。

用法：
  python etf_momentum_v2.py              # 用缓存回测并生成看板(docs/index.html)
  python etf_momentum_v2.py --refresh    # 强制刷新真实数据
  python etf_momentum_v2.py --no-html    # 只跑回测不生成看板
  python etf_momentum_v2.py --email      # 发生调仓时发邮件
  python etf_momentum_v2.py --force-email --no-html   # 发测试邮件验证配置
  python etf_momentum_v2.py --output my_report.html
"""

import argparse
import json
import os
import pickle
from collections import defaultdict
from datetime import datetime

import akshare as ak
import numpy as np


# 加载同目录 .env（若存在），方便配置邮箱而不改动代码；不依赖第三方库
def _load_dotenv(path=".env"):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


_load_dotenv()

import pandas as pd


# =====================================================================
# 配置区
# =====================================================================

# 标的池：代码 -> 显示名称
ETF_UNIVERSE = {
    # ---- 宽基 / 指数 ----
    "sh510300": "沪深300ETF", "sh510500": "中证500ETF", "sz159915": "创业板ETF",
    "sh588000": "科创50ETF",
    # ---- 科技 ----
    "sh512480": "半导体ETF", "sz159995": "芯片ETF", "sh588200": "科创芯片ETF",
    # ---- 金融 / 防御 ----
    "sh512800": "银行ETF", "sh510880": "红利ETF", "sh512000": "券商ETF",
    # ---- 医药 ----
    "sh512010": "医药ETF", "sh512170": "医疗ETF",
    # ---- 消费 ----
    "sh512690": "酒ETF", "sz159928": "消费ETF",
    # ---- 商品 / 避险 ----
    "sh518880": "黄金ETF", "sz159985": "豆粕ETF", "sz159980": "有色ETF",
    # ---- 周期 / 能源（v2 新增/扩充）----
    "sh515220": "煤炭ETF",        # 国泰中证煤炭
    "sz159309": "油气资源ETF",    # 汇添富中证油气资源（159309.SZ）
    "sh561360": "石油ETF",        # 国泰中证油气产业（备选中，默认未启用）
    "sh561760": "油气资源ETF2",   # 博时油气资源（备选中，默认未启用）
    "sz159981": "能源化工ETF",    # 建信郑商所能源化工
    "sh515210": "钢铁ETF",
    "sh512400": "有色金属ETF",
    "sh561160": "电网设备",        # 富国中证电网
    # ---- 海外 ----
    "sh513100": "纳指ETF",
}

# 分类映射（用于分散度检查 + 看板分类饼图）
ETF_CATEGORY = {
    "沪深300ETF": "宽基", "中证500ETF": "宽基", "创业板ETF": "宽基", "科创50ETF": "宽基",
    "半导体ETF": "科技", "芯片ETF": "科技", "科创芯片ETF": "科技",
    "银行ETF": "金融/防御", "红利ETF": "金融/防御", "券商ETF": "金融/防御",
    "医药ETF": "医药", "医疗ETF": "医药",
    "酒ETF": "消费", "消费ETF": "消费",
    "黄金ETF": "商品/避险", "豆粕ETF": "商品/避险", "有色ETF": "商品/避险",
    "煤炭ETF": "周期/能源", "油气资源ETF": "周期/能源", "石油ETF": "周期/能源",
    "油气资源ETF2": "周期/能源", "能源化工ETF": "周期/能源",
    "钢铁ETF": "周期/能源", "有色金属ETF": "周期/能源", "电网设备": "周期/能源",
    "纳指ETF": "海外",
}

# 大盘趋势过滤所用指数
MARKET_INDEX = "sh000001"
BACKTEST_START = "2022-01-01"
BACKTEST_END = "2026-10-08"

# ---- 策略参数 ----
LOOKBACK = 250            # 动量计算窗口（交易日）
TOP_N = 3                 # 持仓数量
MAX_PER_CAT = 1           # 同一大类最多持仓数量（v2 新增）
MA_WINDOW = 250           # 绝对动量均线窗口
REBALANCE_DAYS = 42       # 调仓频率（交易日），约双月
COMMISSION = 0.0005       # 单边手续费
VOLA_THRESH = 0.04        # 20日波动率上限（剔除剧烈震荡）
DROP_THRESH = -0.05       # 近3日跌幅下限（规避急跌）
RISE_THRESH = 0.15        # 近3日涨幅上限（规避疯涨）
MARKET_FILTER = True      # 是否启用大盘趋势过滤
MARKET_MA = 250           # 大盘均线窗口
MARKET_MOMENTUM = 120     # 大盘动量窗口
USE_CASH = True           # 过滤不通过时是否允许空仓

# ---- 邮件通知（QQ邮箱 SMTP，密钥直接内联，单文件即可运行）----
# 注意：QQ邮箱需用「授权码」而非登录密码。
# 开启路径：QQ邮箱网页版 → 设置 → 账户 → 开启 SMTP 服务 → 生成授权码。
# 下面已填好发件/收件与授权码，无需 .env；改这里即可。
# ⚠ 安全提醒：授权码写进代码后，若把本文件推到公开 GitHub 会泄露，请保持仓库私有。
EMAIL_ENABLED = True        # 总开关：True 开启邮件；运行时仍可用 --email / --force-email 控制
EMAIL_SMTP_HOST = "smtp.qq.com"
EMAIL_SMTP_PORT = 465
EMAIL_SENDER = "809080777@qq.com"          # 发件 QQ 号（需开启 SMTP）
EMAIL_AUTH_CODE = "tlntcebonxlnbbgd"       # 授权码（16位，绑定上面发件号）
EMAIL_RECEIVERS = ["809080777@qq.com"]     # 收件邮箱，可写多个如 ["a@qq.com","b@163.com"]

# ---- 路径 ----
DATA_DIR = "data"
RAW_DIR = os.path.join(DATA_DIR, "raw")
PICKLE_FILE = os.path.join(DATA_DIR, "etf_data_v2.pkl")
CACHE_TTL_SEC = 3600 * 6
BATCH_SIZE = 5

# 代码 -> 名称 反查
CODE2NAME = {c: ETF_UNIVERSE.get(c, c) for c in ETF_UNIVERSE}
# 名称 -> 分类（默认归为"其他"）
NAME2CAT = lambda n: ETF_CATEGORY.get(n, "其他")


# =====================================================================
# 数据获取（akshare 版：公开可装、支持 A股 ETF / 指数日线，带本地缓存）
# =====================================================================
import time


def _ak_call(func, *args, retries=4, **kwargs):
    """对 akshare 网络请求做重试，规避数据源偶发重置连接。"""
    last = None
    for i in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:  # ConnectionError / RemoteDisconnected / 空数据等
            last = e
            print(f"    [WARN] 请求失败({i + 1}/{retries}): {type(e).__name__}: {e}")
            time.sleep(1.5 + i)
    raise last


def _ak_etf_close(code, start, end):
    """单只 ETF 日线收盘价（akshare，sina 源）。code 形如 sh510300 / sz159915。"""
    df = _ak_call(ak.fund_etf_hist_sina, symbol=code)
    if df is None or len(df) == 0:
        return None
    df = df.rename(columns={"date": "date", "close": "close"})
    df["date"] = pd.to_datetime(df["date"])
    s = df.set_index("date")["close"].astype(float).sort_index()
    s = s[(s.index >= pd.Timestamp(start)) & (s.index <= pd.Timestamp(end))]
    return s


def _ak_index_close(code, start, end):
    """指数日线收盘价（akshare，sina 源）。code 形如 sh000001（上证指数）。"""
    df = _ak_call(ak.stock_zh_index_daily, symbol=code)
    if df is None or len(df) == 0:
        return None
    df["date"] = pd.to_datetime(df["date"])
    s = df.set_index("date")["close"].astype(float).sort_index()
    s = s[(s.index >= pd.Timestamp(start)) & (s.index <= pd.Timestamp(end))]
    return s


def _recs_to_series(recs):
    df = pd.DataFrame(recs)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["close"].astype(float).sort_index()


def fetch_kline_batch(codes, start, end, use_cache=True):
    os.makedirs(RAW_DIR, exist_ok=True)
    out, todo = {}, []
    for code in codes:
        cache_file = os.path.join(RAW_DIR, f"{code}.json")
        if use_cache and os.path.exists(cache_file):
            age = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(cache_file))).total_seconds()
            if age < CACHE_TTL_SEC:
                with open(cache_file) as f:
                    out[code] = _recs_to_series(json.load(f))
                continue
        todo.append(code)

    for code in todo:
        print(f"  拉取: {code} ({CODE2NAME.get(code, code)})")
        s = _ak_index_close(code, start, end) if code == MARKET_INDEX else _ak_etf_close(code, start, end)
        if s is None or len(s) == 0:
            print(f"  ⚠️ {code} 无数据，跳过")
            continue
        recs = [{"date": d.strftime("%Y-%m-%d"), "close": round(float(v), 4)} for d, v in s.items()]
        with open(os.path.join(RAW_DIR, f"{code}.json"), "w") as f:
            json.dump(recs, f)
        out[code] = s
    return out


def fetch_universe(start=None, end=None, use_cache=True):
    start = start or BACKTEST_START
    end = end or BACKTEST_END
    if use_cache and os.path.exists(PICKLE_FILE):
        print(f"  使用缓存数据: {PICKLE_FILE}")
        with open(PICKLE_FILE, "rb") as f:
            return pickle.load(f)

    print("=" * 60)
    print("获取真实行情数据（akshare）")
    print("=" * 60)
    all_codes = list(ETF_UNIVERSE.keys()) + [MARKET_INDEX]
    all_close = fetch_kline_batch(all_codes, start, end, use_cache)

    etf_close = {c: all_close[c] for c in ETF_UNIVERSE if c in all_close}
    if not etf_close:
        raise RuntimeError("未获取到任何 ETF 数据，请检查网络或 akshare 可用性")
    market = all_close.get(MARKET_INDEX)
    if market is None:
        print("  ⚠️ 未获取到指数数据，大盘过滤将失效")

    price_df = pd.DataFrame(etf_close).dropna(how="all")
    price_df.index = pd.to_datetime(price_df.index)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PICKLE_FILE, "wb") as f:
        pickle.dump((price_df, market), f)
    print(f"  数据已缓存: {len(price_df.columns)} 只ETF, "
          f"{price_df.index[0].date()} ~ {price_df.index[-1].date()}")
    return price_df, market


# =====================================================================
# 选股：动量排名 + 分类上限
# =====================================================================
def select_holdings(cands, top_n=TOP_N, max_per_cat=MAX_PER_CAT):
    """
    在候选 (name, momentum) 列表中，按动量降序选股，
    同时保证同一分类最多持仓 max_per_cat 只，避免同类占满仓位。
    """
    cands = sorted(cands, key=lambda x: -x[1])
    picks, cat_cnt = [], defaultdict(int)
    for name, mom in cands:
        cat = NAME2CAT(name)
        if cat_cnt[cat] >= max_per_cat:
            continue
        picks.append(name)
        cat_cnt[name]  # noqa: 仅占位，避免 lint
        cat_cnt[cat] += 1
        if len(picks) == top_n:
            break
    return picks


# =====================================================================
# 回测引擎
# =====================================================================
class MomentumBacktester:
    def __init__(self, price_df, market_series):
        # 只保留有分类映射的品种，未映射的归入"其他"
        self.codes = [c for c in price_df.columns if CODE2NAME.get(c) in ETF_CATEGORY or True]
        self.names = [CODE2NAME.get(c, c) for c in self.codes]
        self.prices = {c: price_df[c].values for c in self.codes}
        self.dates = price_df.index.values
        self.n = len(price_df)
        if market_series is not None:
            self.market = market_series.reindex(price_df.index).interpolate(
                method="linear").bfill().ffill().values
        else:
            self.market = None
        self.equity = None
        self.trades = []
        self.stats = {}

    def _volatility(self, p, i, w=20):
        if i < w:
            return None
        return np.std(np.diff(np.log(p[i - w + 1:i + 1])))

    def _market_ok(self, i):
        if not MARKET_FILTER or self.market is None:
            return True
        w, w2 = MARKET_MA, MARKET_MOMENTUM
        if i < w:
            return False
        idx = self.market
        ma = np.nanmean(idx[i - w + 1:i + 1])
        if idx[i] < ma:
            return False
        if i >= w2 and idx[i] < idx[i - w2]:
            return False
        return True

    def run(self):
        shares, cash = {}, 1.0
        equity, last_rebal = [], -999
        self.trades = []
        holdings = []
        lb = LOOKBACK

        for i in range(lb, self.n):
            rebal = (i - last_rebal) >= REBALANCE_DAYS
            if rebal:
                last_rebal = i
                mf = self._market_ok(i)
                cands = []
                for c in self.codes:
                    p = self.prices[c]
                    if np.isnan(p[i]) or np.isnan(p[i - lb]):
                        continue
                    mom = p[i] / p[i - lb] - 1
                    ma = np.nanmean(p[i - MA_WINDOW + 1:i + 1])
                    if p[i] < ma:
                        continue
                    chg3 = p[i] / p[i - 3] - 1 if i >= 3 else 0
                    vol = self._volatility(p, i, 20)
                    if vol is None or vol > VOLA_THRESH:
                        continue
                    if chg3 < DROP_THRESH or chg3 > RISE_THRESH:
                        continue
                    cands.append((CODE2NAME.get(c, c), mom))

                # v2：分类上限选股
                ranked = select_holdings(cands, TOP_N, MAX_PER_CAT)
                name2code = {CODE2NAME.get(c, c): c for c in self.codes}

                if mf and ranked:
                    target_codes = [name2code[n] for n in ranked if n in name2code]
                elif USE_CASH:
                    target_codes = []
                else:
                    target_codes = list(shares.keys())

                if set(shares.keys()) != set(target_codes):
                    for c, s in list(shares.items()):
                        if not np.isnan(self.prices[c][i]):
                            cash += s * self.prices[c][i] * (1 - COMMISSION)
                    shares.clear()
                    if target_codes:
                        for c in target_codes:
                            shares[c] = cash / (len(target_codes) * self.prices[c][i]) * (1 - COMMISSION)
                        cash = 0
                    self.trades.append({
                        "date": pd.Timestamp(self.dates[i]).strftime("%Y-%m-%d"),
                        "names": ranked if ranked else ["现金"],
                        "cats": [NAME2CAT(n) for n in ranked] if ranked else ["现金"],
                    })
                    holdings = target_codes

            total = cash
            for c, s in shares.items():
                if not np.isnan(self.prices[c][i]):
                    total += s * self.prices[c][i]
            equity.append(total)

        self.equity = pd.Series(equity, index=pd.to_datetime(self.dates[lb:]))
        self._calc_stats()
        return self

    def _calc_stats(self):
        eq = self.equity
        rets = eq.pct_change().dropna()
        nav = eq.iloc[-1] / eq.iloc[0]
        years = len(rets) / 252
        # 分类分散度
        cat_cnt = defaultdict(int)
        for t in self.trades:
            for cat in t.get("cats", []):
                if cat != "现金":
                    cat_cnt[cat] += 1
        self.stats = {
            "start": eq.index[0].strftime("%Y-%m-%d"),
            "end": eq.index[-1].strftime("%Y-%m-%d"),
            "years": years,
            "total_return": nav - 1,
            "annual_return": (nav ** (1 / years) - 1) if years > 0 else 0,
            "max_drawdown": ((eq - eq.cummax()) / eq.cummax()).min(),
            "sharpe": rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0,
            "volatility": rets.std() * np.sqrt(252),
            "trades": len(self.trades),
            "cat_count": dict(cat_cnt),
        }


def benchmark(price_df):
    valid = price_df.dropna(how="any")
    log_r = np.diff(np.log(valid.values), axis=0)
    nav = np.exp(np.cumsum(np.nanmean(log_r, axis=1)))
    idx = valid.index[1:]
    rets = np.diff(np.log(nav))
    return {
        "nav": pd.Series(nav, index=idx),
        "total_return": nav[-1] / nav[0] - 1,
        "annual_return": ((nav[-1] / nav[0]) ** (252 / len(nav)) - 1),
        "max_drawdown": ((nav - np.maximum.accumulate(nav)) / np.maximum.accumulate(nav)).min(),
        "sharpe": rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0,
        "volatility": rets.std() * np.sqrt(252),
    }


# =====================================================================
# HTML 看板生成
# =====================================================================
def _series_to_ec(s):
    return [[d.strftime("%Y-%m-%d"), round(float(v), 4)] for d, v in s.items() if v == v]


def _yearly(nav):
    out = []
    for y, sub in sorted(nav.groupby(nav.index.year)):
        if len(sub) < 2:
            continue
        r = sub.iloc[-1] / sub.iloc[0] - 1
        dd = ((sub - sub.cummax()) / sub.cummax()).min()
        out.append([str(y), round(r * 100, 2), round(dd * 100, 2)])
    return out


def _holdings_pie(trades):
    cnt = {}
    for t in trades:
        for nm in t["names"]:
            if nm == "现金":
                continue
            cnt[nm] = cnt.get(nm, 0) + 1
    return [{"name": k, "value": v} for k, v in sorted(cnt.items(), key=lambda x: -x[1])]


def _category_pie(trades):
    cnt = {}
    for t in trades:
        for cat in t.get("cats", []):
            if cat == "现金":
                continue
            cnt[cat] = cnt.get(cat, 0) + 1
    return [{"name": k, "value": v} for k, v in sorted(cnt.items(), key=lambda x: -x[1])]


def _tag_html(items, cls="tag"):
    return "".join(f"<span class='{cls}'>{x}</span>" for x in items)


def build_html(result, bench, output_path):
    s = result.stats
    eq, trades = result.equity, result.trades
    strategy_curve = json.dumps(_series_to_ec(eq / eq.iloc[0]), ensure_ascii=False)
    bench_curve = json.dumps(_series_to_ec(bench["nav"] / bench["nav"].iloc[0]), ensure_ascii=False)
    yearly = json.dumps(_yearly(eq), ensure_ascii=False)
    pie = json.dumps(_holdings_pie(trades), ensure_ascii=False)
    cat_pie = json.dumps(_category_pie(trades), ensure_ascii=False)

    trade_rows = []
    for t in reversed(trades):
        names = t["names"]
        cats = t.get("cats", [])
        if names == ["现金"]:
            cells = f"<td colspan='{TOP_N}'><span class='tag cash'>现金</span></td>"
        else:
            cells = "".join(
                f"<td><span class='tag'>{n}</span><br>"
                f"<span class='tag cat'>{c}</span></td>"
                for n, c in zip(names, cats)
            )
        trade_rows.append(f"<tr><td>{t['date']}</td>{cells}</tr>")
    trade_table = "\n".join(trade_rows) or f"<tr><td colspan='{1+TOP_N}'>无调仓记录</td></tr>"

    params = [
        ("动量窗口", f"{LOOKBACK}日"), ("持仓数量", f"{TOP_N}只"),
        ("同类上限", f"{MAX_PER_CAT}只/类"), ("绝对动量均线", f"{MA_WINDOW}日均线"),
        ("调仓频率", f"约每{REBALANCE_DAYS}个交易日"),
        ("大盘过滤", "开启" if MARKET_FILTER else "关闭"), ("大盘均线", f"{MARKET_MA}日"),
        ("大盘动量", f"{MARKET_MOMENTUM}日"), ("允许空仓", "是" if USE_CASH else "否"),
        ("波动率上限", f"{VOLA_THRESH:.0%}"), ("3日跌幅下限", f"{DROP_THRESH:.0%}"),
        ("3日涨幅上限", f"{RISE_THRESH:.0%}"),
    ]
    param_rows = "\n".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in params)

    cat_dist = s.get("cat_count", {})
    cat_rows = "\n".join(
        f"<tr><td><span class='tag cat'>{k}</span></td><td>{v} 次</td></tr>"
        for k, v in sorted(cat_dist.items(), key=lambda x: -x[1])
    ) or "<tr><td colspan='2'>无数据</td></tr>"

    def card(label, val, sub="", cls=""):
        return (f"<div class='card {cls}'><div class='card-label'>{label}</div>"
                f"<div class='card-value'>{val}</div><div class='card-sub'>{sub}</div></div>")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ETF 长周期双动量策略 v2 回测看板</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif; background:#0f172a;
  color:#e2e8f0; line-height:1.6; padding:24px; }}
.wrap {{ max-width:1200px; margin:0 auto; }}
h1 {{ font-size:26px; font-weight:700; }}
.subtitle {{ color:#94a3b8; font-size:14px; margin:6px 0 24px; }}
.section {{ background:#1e293b; border-radius:16px; padding:24px; margin-bottom:20px;
  box-shadow:0 4px 24px rgba(0,0,0,.25); }}
.section-title {{ font-size:18px; font-weight:600; margin-bottom:18px; padding-left:12px;
  border-left:4px solid #3b82f6; }}
.grid {{ display:grid; gap:14px; }}
.grid.cols-4 {{ grid-template-columns:repeat(4,1fr); }}
.grid.cols-2 {{ grid-template-columns:1fr 1fr; }}
@media(max-width:860px){{ .grid.cols-4,.grid.cols-2{{grid-template-columns:1fr 1fr;}} }}
@media(max-width:560px){{ .grid.cols-4,.grid.cols-2{{grid-template-columns:1fr;}} }}
.card {{ background:#0f172a; border-radius:12px; padding:18px; }}
.card-label {{ font-size:13px; color:#94a3b8; }}
.card-value {{ font-size:28px; font-weight:700; margin:6px 0 2px; }}
.card-sub {{ font-size:12px; color:#64748b; }}
.up {{ color:#22c55e; }} .down {{ color:#ef4444; }}
.chart {{ width:100%; height:380px; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
th,td {{ padding:10px 12px; text-align:left; border-bottom:1px solid #334155; }}
th {{ color:#94a3b8; font-weight:500; font-size:13px; }}
.rebalance-wrap {{ max-height:440px; overflow:auto; border-radius:10px; scrollbar-width:none; }}
.rebalance-wrap::-webkit-scrollbar {{ display:none; }}
.rebalance {{ table-layout:fixed; }}
.rebalance thead th {{ position:sticky; top:0; background:#1e293b; z-index:1; }}
.rebalance th, .rebalance td {{ text-align:center; vertical-align:top; }}
.rebalance th:first-child, .rebalance td:first-child {{ text-align:left; width:100px; white-space:nowrap; }}
.rebalance td {{ width:calc((100% - 100px) / {TOP_N}); min-width:120px; }}
.tag {{ display:inline-block; background:#1e3a5f; color:#60a5fa; border-radius:6px;
  padding:2px 8px; font-size:12px; margin:2px 4px 2px 0; }}
.tag.cash {{ background:#3b2f1e; color:#f59e0b; }}
.tag.cat {{ background:#2d2a1f; color:#d97706; font-size:11px; }}
.note {{ font-size:12px; color:#64748b; margin-top:14px; line-height:1.8; }}
.badge {{ display:inline-block; background:#3b82f6; color:#fff; border-radius:999px;
  padding:2px 10px; font-size:12px; margin-left:8px; vertical-align:middle; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>📈 ETF 长周期双动量策略<span class="badge">v2</span></h1>
  <div class="subtitle">数据区间 {s['start']} ~ {s['end']} ｜ 样本 {s['years']:.1f} 年 ｜ 标的池 {len(result.codes)} 只 ETF</div>

  <div class="section">
    <div class="section-title">核心绩效</div>
    <div class="grid cols-4">
      {card("策略年化", f"{s['annual_return']:>+.2%}", "复合年化收益率", "up" if s['annual_return']>0 else "down")}
      {card("基准年化", f"{bench['annual_return']:>+.2%}", "等权持有", "up" if bench['annual_return']>0 else "down")}
      {card("超额收益", f"{(s['annual_return']-bench['annual_return']):+.2%}", "策略 - 基准")}
      {card("策略回撤", f"{s['max_drawdown']:.2%}", "最大回撤", "down")}
      {card("基准回撤", f"{bench['max_drawdown']:.2%}", "等权最大回撤")}
      {card("策略 Sharpe", f"{s['sharpe']:.2f}", "风险调整后收益")}
      {card("基准 Sharpe", f"{bench['sharpe']:.2f}", "基准 Sharpe")}
      {card("策略波动率", f"{s['volatility']:.2%}", "年化标准差")}
    </div>
  </div>

  <div class="section"><div class="section-title">净值曲线</div><div class="chart" id="curveChart"></div></div>
  <div class="section"><div class="section-title">分年度表现</div><div class="chart" id="yearChart" style="height:320px;"></div></div>

  <div class="section">
    <div class="section-title">调仓记录（共 {s['trades']} 次）· 含分类</div>
    <div class="rebalance-wrap"><table class="rebalance"><thead><tr><th>调仓日</th><th colspan="3">持仓标的 / 分类</th></tr></thead><tbody>{trade_table}</tbody></table></div>
  </div>

  <div class="grid cols-2">
    <div class="section"><div class="section-title">持仓偏好（品种）</div><div class="chart" id="pieChart" style="height:340px;"></div></div>
    <div class="section"><div class="section-title">持仓偏好（分类）</div><div class="chart" id="catPieChart" style="height:340px;"></div></div>
  </div>

  <div class="section">
    <div class="section-title">分类分散度（按调仓次数统计）</div>
    <table><thead><tr><th>分类</th><th>出现次数</th></tr></thead><tbody>{cat_rows}</tbody></table>
    <div class="note">出现次数越多，说明该分类在回测期间越常被策略选中。理想状态下应分布较均匀，避免单一分类长期主导仓位。</div>
  </div>

  <div class="section">
    <div class="section-title">策略参数</div>
    <table><tbody>{param_rows}</tbody></table>
  </div>

  <div class="section">
    <div class="note">⚠️ <b>免责声明</b>：本看板基于历史行情数据的回测结果，仅用于策略思路验证，不构成任何投资建议。
    历史表现不代表未来收益，样本区间有限（{s['years']:.1f} 年），存在参数过拟合与结构性行情偏差风险。实盘前请充分评估自身风险承受能力。</div>
  </div>
</div>

<script>
const strategyData = {strategy_curve};
const benchData = {bench_curve};
const yearData = {yearly};
const pieData = {pie};
const catData = {cat_pie};

const baseTextStyle = {{color:'#e2e8f0'}};
const baseLineColor = '#334155';

echarts.init(document.getElementById('curveChart')).setOption({{
  backgroundColor:'transparent',
  tooltip:{{trigger:'axis', backgroundColor:'#0f172a', borderColor:baseLineColor, textStyle:baseTextStyle}},
  legend:{{data:['策略净值','等权基准'], textStyle:{{color:'#94a3b8'}}, top:0}},
  grid:{{left:'3%',right:'4%',bottom:'3%',top:40,containLabel:true}},
  xAxis:{{type:'time', axisLine:{{lineStyle:{{color:baseLineColor}}}}, axisLabel:{{color:'#94a3b8'}}}},
  yAxis:{{type:'value', scale:true, axisLine:{{lineStyle:{{color:baseLineColor}}}},
    splitLine:{{lineStyle:{{color:'#1e293b'}}}}, axisLabel:{{color:'#94a3b8', formatter:v=>(v*100).toFixed(0)+'%'}}}},
  series:[
    {{name:'策略净值', type:'line', data:strategyData, showSymbol:false,
      lineStyle:{{width:2.5, color:'#3b82f6'}}, areaStyle:{{color:'rgba(59,130,246,.12)'}}}},
    {{name:'等权基准', type:'line', data:benchData, showSymbol:false,
      lineStyle:{{width:2, color:'#94a3b8', type:'dashed'}}}}
  ]
}});

const years = yearData.map(d=>d[0]);
echarts.init(document.getElementById('yearChart')).setOption({{
  backgroundColor:'transparent',
  tooltip:{{trigger:'axis', backgroundColor:'#0f172a', borderColor:baseLineColor, textStyle:baseTextStyle}},
  legend:{{data:['年度收益','年度回撤'], textStyle:{{color:'#94a3b8'}}, top:0}},
  grid:{{left:'3%',right:'4%',bottom:'3%',top:40,containLabel:true}},
  xAxis:{{type:'category', data:years, axisLine:{{lineStyle:{{color:baseLineColor}}}}, axisLabel:{{color:'#94a3b8'}}}},
  yAxis:{{type:'value', axisLine:{{lineStyle:{{color:baseLineColor}}}},
    splitLine:{{lineStyle:{{color:'#1e293b'}}}}, axisLabel:{{color:'#94a3b8', formatter:v=>v+'%'}}}},
  series:[
    {{name:'年度收益', type:'bar', data:yearData.map(d=>d[1]),
      color:'#22c55e',
      itemStyle:{{color:p=>p.value>=0?'#22c55e':'#ef4444', borderRadius:[4,4,0,0]}}}},
    {{name:'年度回撤', type:'bar', data:yearData.map(d=>d[2]),
      color:'#ef4444',
      itemStyle:{{color:'rgba(239,68,68,.5)', borderRadius:[4,4,0,0]}}}}
  ]
}});

const pieOpt = (data)=>({{backgroundColor:'transparent', tooltip:{{backgroundColor:'#0f172a', borderColor:baseLineColor, textStyle:baseTextStyle}},
  series:[{{type:'pie', radius:['40%','70%'], data:data.length?data:[{{value:1,name:'无数据'}}],
  label:{{color:'#e2e8f0', formatter:'{{b}} {{d}}%'}},
  itemStyle:{{borderColor:'#1e293b', borderWidth:2}}}}]}});
echarts.init(document.getElementById('pieChart')).setOption(pieOpt(pieData));
echarts.init(document.getElementById('catPieChart')).setOption(pieOpt(catData));
</script>
</body>
</html>"""

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  看板已生成: {output_path}")


# =====================================================================
# 邮件通知（QQ邮箱 SMTP，默认关闭，需 --email 或环境变量开启）
# =====================================================================
def send_rebalance_email(result, bench, dry_run=False):
    """把最近一次调仓信息通过 QQ邮箱 SMTP 发送出去；dry_run 仅打印不发送。"""
    s = result.stats
    trades = result.trades
    if not trades:
        print("  [WARN] 无调仓记录，跳过邮件")
        return False

    t = trades[-1]
    names = t.get("names", [])
    cats = t.get("cats", [])
    if names == ["现金"]:
        hold_lines = "  - 现金（空仓）"
    else:
        hold_lines = "\n".join(
            f"  - {n}（{c}）" for n, c in zip(names, cats)
        ) or "  - （无）"

    subject = f"[ETF双动量] 调仓通知 {t['date']}"
    body = (
        "ETF 长周期双动量策略 · 调仓通知（模拟/回测）\n"
        "----------------------------------------\n"
        f"调仓日    ：{t['date']}\n"
        f"本次持仓 ：\n{hold_lines}\n\n"
        "区间绩效  ：\n"
        f"  策略年化 {s['annual_return']:+.2%} ｜ 基准年化 {bench['annual_return']:+.2%}\n"
        f"  策略总收益 {s['total_return']:+.2%} ｜ 最大回撤 {s['max_drawdown']:.2%}"
        f" ｜ Sharpe {s['sharpe']:.2f}\n"
        "----------------------------------------\n"
        f"累计调仓 {s['trades']} 次 ｜ 区间 {s['start']} ~ {s['end']}\n"
    )

    if dry_run:
        print("  [DRY] 邮件内容预览：\n" + body)
        return True

    if not (EMAIL_SENDER and EMAIL_AUTH_CODE and EMAIL_RECEIVERS):
        print("  [WARN] 邮件未发送：请先配置 ETF_EMAIL_SENDER / ETF_EMAIL_AUTH / ETF_EMAIL_TO")
        return False
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.header import Header
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = EMAIL_SENDER
        msg["To"] = ", ".join(EMAIL_RECEIVERS)
        msg["Subject"] = Header(subject, "utf-8")
        with smtplib.SMTP_SSL(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, timeout=30) as svr:
            svr.login(EMAIL_SENDER, EMAIL_AUTH_CODE)
            svr.sendmail(EMAIL_SENDER, EMAIL_RECEIVERS, msg.as_string())
        print(f"  邮件已发送至：{', '.join(EMAIL_RECEIVERS)}")
        return True
    except Exception as e:
        print(f"  [WARN] 邮件发送失败：{type(e).__name__}: {e}")
        return False


# =====================================================================
# 主入口
# =====================================================================
def main():
    parser = argparse.ArgumentParser(description="ETF 长周期双动量策略回测 v2（单文件版）")
    parser.add_argument("--refresh", action="store_true", help="强制重新拉取行情数据")
    parser.add_argument("--no-html", action="store_true", help="不生成 HTML 看板")
    parser.add_argument("--output", default="docs/index.html", help="看板输出路径")
    parser.add_argument("--email", action="store_true", help="发送调仓邮件通知（QQ邮箱SMTP）")
    parser.add_argument("--force-email", action="store_true",
                        help="强制发送调仓邮件（忽略'是否发生调仓'判断，仅用于测试真实发送）")
    args = parser.parse_args()

    price_df, market = fetch_universe(use_cache=not args.refresh)
    print(f"\n  标的池: {len(price_df.columns)} 只 ETF")
    print(f"  区间:   {price_df.index[0].date()} ~ {price_df.index[-1].date()}")
    print(f"  交易日: {len(price_df)} 天")

    print("\n" + "=" * 64)
    print("  运行策略回测 (v2)")
    print("=" * 64)
    bt = MomentumBacktester(price_df, market).run()
    bmark = benchmark(price_df)

    print("\n" + "=" * 64)
    print("  结果对比")
    print("=" * 64)
    print(f"  {'指标':<14}{'策略':>12}{'基准':>12}")
    print(f"  {'─'*38}")
    print(f"  {'年化收益':<14}{bt.stats['annual_return']:>+12.2%}{bmark['annual_return']:>+12.2%}")
    print(f"  {'总收益':<14}{bt.stats['total_return']:>+12.2%}{bmark['total_return']:>+12.2%}")
    print(f"  {'最大回撤':<14}{bt.stats['max_drawdown']:>12.2%}{bmark['max_drawdown']:>12.2%}")
    print(f"  {'Sharpe':<14}{bt.stats['sharpe']:>12.2f}{bmark['sharpe']:>12.2f}")
    print(f"  {'波动率':<14}{bt.stats['volatility']:>11.2%}{bmark['volatility']:>12.2%}")
    print(f"  {'调仓次数':<14}{bt.stats['trades']:>12d}{'—':>12}")
    print(f"  {'区间':<14}{bt.stats['start']}>{bt.stats['end']}")

    if bt.trades:
        print(f"\n  调仓记录 ({len(bt.trades)} 次):")
        for t in bt.trades:
            print(f"    {t['date']} → {', '.join(t['names'])}")

    cat_cnt = bt.stats.get("cat_count", {})
    if cat_cnt:
        print(f"\n  分类分散度:")
        for cat, cnt in sorted(cat_cnt.items(), key=lambda x: -x[1]):
            print(f"    {cat:<12}{cnt} 次")

    if not args.no_html:
        build_html(bt, bmark, args.output)

    if args.email or EMAIL_ENABLED or args.force_email:
        last_date = price_df.index[-1].strftime("%Y-%m-%d")
        latest = bt.trades[-1]["date"] if bt.trades else None
        # 仅当最近一次调仓发生在最新交易日（即本次运行确实触发了调仓）才发信
        if latest == last_date or args.force_email:
            send_rebalance_email(bt, bmark)
        else:
            print(f"  [INFO] 最近调仓 {latest} ≠ 最新交易日 {last_date}，本次无新调仓，跳过邮件")

    print("\n  完成 ✓")


if __name__ == "__main__":
    main()
