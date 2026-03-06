"""
Dividend Pool Page Generator

生成高股息养老股池的独立 HTML 解释页面。
包含：选股逻辑说明、当前池子完整表格（含派息类型）、版本历史。
"""
from html import escape as _esc
from typing import List, Dict, Any


def generate_dividend_pool_page(
    versions: List[Dict[str, Any]],
    pool_records: List[Dict[str, Any]],
    current_version: str,
) -> str:
    """生成 dividend_pool.html 独立页面。

    Args:
        versions: list of {version, created_at, tickers_count, avg_quality_score}
        pool_records: list of pool rows from get_pool_by_version()
        current_version: version string to highlight as current

    Returns:
        Complete HTML string.
    """
    pool_table = _pool_table(pool_records)
    version_list = _version_list(versions, current_version)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>高股息养老股池 — 选股逻辑</title>
{_css()}
</head>
<body>
<div class="container">
  <h1>高股息养老股池 <span class="subtitle">长期吃股息 · 养老防御</span></h1>

  <section class="methodology">
    <h2>选股逻辑</h2>
    <p>参考 <strong>SCHD（Schwab US Dividend Equity ETF）</strong> 方法论，覆盖美股、港股、A股，月度更新。目标：高确定性、基本面稳健、适合长期持有吃股息。</p>

    <h3>硬性筛选规则</h3>
    <table class="rules-table">
      <tr><th>规则</th><th>阈值</th><th>说明</th></tr>
      <tr><td>连续派息年限</td><td>≥ 5 年</td><td>至少经历一个完整市场周期</td></tr>
      <tr><td>当前股息率</td><td>≥ 2.0%</td><td>过滤名义派息但收益极低的标的</td></tr>
      <tr><td>5 年股息增长率</td><td>≥ 0%</td><td>排除持续削减股息的标的</td></tr>
      <tr><td>派息率（行业感知）</td><td>≤ 100%</td><td>见下方行业说明</td></tr>
      <tr><td>股息质量综合评分</td><td>≥ 70</td><td>稳定性×40% + 财务健康×40% + 防御性×20%</td></tr>
    </table>

    <h3>派息率行业分类逻辑</h3>
    <p>GAAP 净利润对资本密集型行业存在严重失真（大量折旧摊销压低净利润），因此按行业选择不同指标：</p>
    <table class="rules-table">
      <tr><th>行业</th><th>使用指标</th><th>原因</th></tr>
      <tr>
        <td><span class="badge badge-fcf">Energy</span> <span class="badge badge-fcf">Utilities</span> <span class="badge badge-fcf">Real Estate</span></td>
        <td><strong>FCF 派息率</strong><br>年度股息 / 自由现金流</td>
        <td>管道/电力/REIT 资产折旧周期 20-40 年，D&amp;A 极大，GAAP 净利润严重低估真实盈利能力</td>
      </tr>
      <tr>
        <td>其他行业</td>
        <td><strong>GAAP 派息率</strong><br>股息 / 净利润</td>
        <td>轻资产行业 D&amp;A 影响较小，GAAP 派息率准确</td>
      </tr>
    </table>
  </section>

  <section class="pool-section">
    <h2>当前池子
      <span class="version-badge">{_esc(current_version)}</span>
      <span class="count-badge">{len(pool_records)} 支标的</span>
    </h2>
    {pool_table}
  </section>

  <section class="versions-section">
    <h2>版本历史</h2>
    {version_list}
  </section>
</div>
</body>
</html>"""


def _pool_table(records: List[Dict]) -> str:
    if not records:
        return '<p class="empty">当前池子为空</p>'

    rows = []
    for r in records:
        payout_badge = (
            '<span class="badge badge-fcf">FCF</span>'
            if r.get("payout_type") == "FCF"
            else '<span class="badge badge-gaap">GAAP</span>'
        )
        yield_str = f"{r['dividend_yield']:.1f}%" if r.get('dividend_yield') else "N/A"
        payout_str = f"{r['payout_ratio']:.0f}%" if r.get('payout_ratio') else "N/A"
        score_str = f"{r['quality_score']:.0f}" if r.get('quality_score') else "N/A"
        growth_str = f"{r['dividend_growth_5y']:+.1f}%" if r.get('dividend_growth_5y') is not None else "N/A"
        rows.append(f"""
      <tr>
        <td class="ticker">{_esc(r['ticker'])}</td>
        <td>{_esc(r.get('name') or r['ticker'])}</td>
        <td><span class="market-badge">{_esc(r.get('market', ''))}</span></td>
        <td class="score">{score_str}</td>
        <td>{r.get('consecutive_years', 'N/A')}年</td>
        <td>{yield_str}</td>
        <td>{payout_badge} {payout_str}</td>
        <td>{growth_str}</td>
        <td>{_esc(r.get('sector') or '')}</td>
      </tr>""")

    return f"""<table class="pool-table">
    <thead>
      <tr>
        <th>代码</th><th>名称</th><th>市场</th><th>评分</th>
        <th>连续年限</th><th>股息率</th><th>派息率</th><th>5年增长</th><th>行业</th>
      </tr>
    </thead>
    <tbody>{''.join(rows)}
    </tbody>
  </table>"""


def _version_list(versions: List[Dict], current: str) -> str:
    if not versions:
        return '<p class="empty">暂无历史版本</p>'
    rows = []
    for v in versions:
        cls = "version-row current" if v["version"] == current else "version-row"
        created = v.get("created_at", "")[:16].replace("T", " ")
        rows.append(f"""
    <tr class="{cls}">
      <td>{_esc(v['version'])}</td>
      <td>{_esc(created)}</td>
      <td>{v.get('tickers_count', 0)} 支</td>
      <td>{v.get('avg_quality_score', 0):.1f}</td>
    </tr>""")
    return f"""<table class="version-table">
  <thead><tr><th>版本</th><th>筛选时间</th><th>入池数</th><th>平均评分</th></tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>"""


def _css() -> str:
    return """<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', sans-serif;
       background: #0d1117; color: #c9d1d9; line-height: 1.6; }
.container { max-width: 1100px; margin: 0 auto; padding: 2rem; }
h1 { font-size: 1.8rem; color: #f0f6fc; margin-bottom: 0.3rem; }
h2 { font-size: 1.2rem; color: #58a6ff; margin: 2rem 0 0.8rem; border-bottom: 1px solid #30363d; padding-bottom: 0.4rem; }
h3 { font-size: 1rem; color: #8b949e; margin: 1.2rem 0 0.5rem; }
.subtitle { font-size: 0.9rem; color: #8b949e; font-weight: 400; margin-left: 0.5rem; }
section { margin-bottom: 2.5rem; }
p { color: #8b949e; margin-bottom: 0.8rem; }
table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
th { background: #161b22; color: #8b949e; padding: 0.5rem 0.7rem; text-align: left; font-weight: 500; }
td { padding: 0.45rem 0.7rem; border-bottom: 1px solid #21262d; }
tr:hover td { background: #161b22; }
.ticker { font-weight: 600; color: #f0f6fc; font-family: monospace; }
.score { font-weight: 600; color: #3fb950; }
.empty { color: #8b949e; font-style: italic; padding: 1rem 0; }
.badge { display: inline-block; padding: 0.1rem 0.45rem; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
.badge-fcf  { background: #1f4a2e; color: #3fb950; }
.badge-gaap { background: #1a2942; color: #58a6ff; }
.market-badge { background: #21262d; color: #8b949e; padding: 0.1rem 0.35rem; border-radius: 3px; font-size: 0.75rem; }
.version-badge { background: #1f4a2e; color: #3fb950; padding: 0.15rem 0.5rem; border-radius: 4px; font-size: 0.8rem; margin-left: 0.5rem; }
.count-badge   { background: #1a2942; color: #58a6ff; padding: 0.15rem 0.5rem; border-radius: 4px; font-size: 0.8rem; }
.version-row.current td { color: #3fb950; }
</style>"""
