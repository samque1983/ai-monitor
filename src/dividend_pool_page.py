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
    avg_score = (
        sum(r.get("quality_score") or 0 for r in pool_records) / len(pool_records)
        if pool_records else 0
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>高股息养老股池 · {_esc(current_version)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=DM+Sans:opsz,wght@9..40,300..600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
{_css()}
</head>
<body>
<div class="container">

<div class="page-eyebrow">
  <span class="eyebrow-label">Dividend Pool</span>
  <span class="eyebrow-date">{_esc(current_version)}</span>
</div>
<h1 class="page-title">高股息养老股池</h1>
<div class="badges">
  <span class="badge badge-green"><span class="badge-dot"></span>{len(pool_records)} 支标的</span>
  <span class="badge badge-blue"><span class="badge-dot"></span>均分 {avg_score:.0f}</span>
  <span class="badge badge-subtle">长期吃股息 · 养老防御</span>
</div>

<div class="summary">
  <div class="summary-hero">
    <div class="stat">
      <div class="stat-label">选股方法论</div>
      <div class="stat-value" style="font-size:16px;letter-spacing:0">SCHD 方法论</div>
      <div class="stat-note">覆盖美股、港股、A股，月度更新</div>
    </div>
    <div class="stat">
      <div class="stat-label">质量评分门槛</div>
      <div class="stat-value">≥ 70</div>
      <div class="stat-note">稳定性×40% + 财务健康×40% + 防御性×20%</div>
    </div>
    <div class="stat">
      <div class="stat-label">连续派息门槛</div>
      <div class="stat-value">≥ 5 年</div>
      <div class="stat-note">至少经历一个完整市场周期</div>
    </div>
  </div>
</div>

<div class="section-header">
  <span class="section-label">选股规则</span>
  <div class="section-rule"></div>
</div>
<div class="rules-card">
  <div class="rules-grid">
    <div class="rule-item">
      <div class="rule-label">当前股息率</div>
      <div class="rule-value">≥ 2.0%</div>
      <div class="rule-note">过滤名义派息但收益极低的标的</div>
    </div>
    <div class="rule-item">
      <div class="rule-label">5 年股息增长率</div>
      <div class="rule-value">≥ 0%</div>
      <div class="rule-note">排除持续削减股息的标的</div>
    </div>
    <div class="rule-item">
      <div class="rule-label">派息率（行业感知）</div>
      <div class="rule-value">≤ 100%</div>
      <div class="rule-note">Energy/Utilities/Real Estate 用 FCF 派息率</div>
    </div>
    <div class="rule-item">
      <div class="rule-label">FCF 适用行业</div>
      <div class="rule-value" style="font-size:13px">能源 · 公用 · 地产</div>
      <div class="rule-note">D&A 极大，GAAP 净利润严重低估盈利能力</div>
    </div>
  </div>
</div>

<div class="section-header" style="margin-top:32px">
  <span class="section-label">当前池子</span>
  <div class="section-rule"></div>
  <span class="section-label">{len(pool_records)} 支</span>
</div>
{pool_table}

<div class="section-header" style="margin-top:32px">
  <span class="section-label">版本历史</span>
  <div class="section-rule"></div>
  <span class="section-label">{len(versions)} 期</span>
</div>
{version_list}

</div>
</body>
</html>"""


def _pool_table(records: List[Dict]) -> str:
    if not records:
        return '<p class="empty-state">当前池子为空</p>'

    rows = []
    for r in records:
        payout_badge = (
            '<span class="badge badge-green" style="padding:2px 7px;font-size:10px">FCF</span>'
            if r.get("payout_type") == "FCF"
            else '<span class="badge badge-blue" style="padding:2px 7px;font-size:10px">GAAP</span>'
        )
        yield_str = f"{r['dividend_yield']:.1f}%" if r.get('dividend_yield') else "—"
        payout_str = f"{r['payout_ratio']:.0f}%" if r.get('payout_ratio') else "—"
        score_val = r.get('quality_score')
        score_color = "#34c759" if (score_val or 0) >= 80 else ("#ffb340" if (score_val or 0) >= 70 else "#ff453a")
        score_str = f"{score_val:.0f}" if score_val else "—"
        growth_val = r.get('dividend_growth_5y')
        growth_str = f"{growth_val:+.1f}%" if growth_val is not None else "—"
        growth_color = "#34c759" if (growth_val or 0) >= 5 else ("#ffb340" if (growth_val or 0) >= 0 else "#ff453a")
        market = r.get('market', '')
        rows.append(f"""
      <tr>
        <td><span class="ticker-chip">{_esc(r['ticker'])}</span></td>
        <td class="name-cell">{_esc(r.get('name') or r['ticker'])}</td>
        <td><span class="market-chip">{_esc(market)}</span></td>
        <td style="color:{score_color};font-family:'DM Mono',monospace;font-weight:600">{score_str}</td>
        <td style="font-family:'DM Mono',monospace;color:var(--text-2)">{r.get('consecutive_years', '—')}y</td>
        <td style="font-family:'DM Mono',monospace;color:var(--text)">{yield_str}</td>
        <td>{payout_badge} <span style="font-family:'DM Mono',monospace;font-size:12px;color:var(--text-2)">{payout_str}</span></td>
        <td style="font-family:'DM Mono',monospace;color:{growth_color}">{growth_str}</td>
        <td style="color:var(--text-3);font-size:12px">{_esc(r.get('sector') or '')}</td>
      </tr>""")

    return f"""<div class="table-wrap">
  <table class="pool-table">
    <thead>
      <tr>
        <th>代码</th><th>名称</th><th>市场</th><th>评分</th>
        <th>连续年限</th><th>股息率</th><th>派息率</th><th>5年增长</th><th>行业</th>
      </tr>
    </thead>
    <tbody>{''.join(rows)}
    </tbody>
  </table>
</div>"""


def _version_list(versions: List[Dict], current: str) -> str:
    if not versions:
        return '<p class="empty-state">暂无历史版本</p>'
    rows = []
    for v in versions:
        is_current = v["version"] == current
        created = v.get("created_at", "")[:16].replace("T", " ")
        cur_marker = '<span class="badge badge-green" style="padding:2px 7px;font-size:10px;margin-left:6px">当前</span>' if is_current else ""
        rows.append(f"""
    <tr{"" if not is_current else ' class="version-current"'}>
      <td><span style="font-family:'DM Mono',monospace;font-size:12px">{_esc(v['version'])}</span>{cur_marker}</td>
      <td style="font-family:'DM Mono',monospace;font-size:12px;color:var(--text-3)">{_esc(created)}</td>
      <td style="font-family:'DM Mono',monospace;color:var(--text-2)">{v.get('tickers_count', 0)} 支</td>
      <td style="font-family:'DM Mono',monospace;color:var(--text-2)">{v.get('avg_quality_score', 0):.1f}</td>
    </tr>""")
    return f"""<div class="table-wrap">
  <table class="pool-table">
    <thead><tr><th>版本</th><th>筛选时间</th><th>入池数</th><th>平均评分</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</div>"""


def _css() -> str:
    return """<style>
/* ── Reset ───────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

/* ── Tokens ──────────────────────────────── */
:root {
  --bg:        #080808;
  --surface:   #101010;
  --surface-2: #181818;
  --border:    rgba(255,255,255,0.08);
  --border-2:  rgba(255,255,255,0.05);
  --text:      #ececec;
  --text-2:    rgba(236,236,236,0.58);
  --text-3:    rgba(236,236,236,0.38);
  --red:       #ff453a;
  --amber:     #ffb340;
  --green:     #34c759;
  --blue:      #0a84ff;
  --r4: 4px; --r8: 8px; --r12: 12px; --r16: 16px; --r24: 24px;
}

/* ── Base ────────────────────────────────── */
body {
  background: var(--bg);
  color: var(--text);
  font-family: "DM Sans", -apple-system, "Helvetica Neue", sans-serif;
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  padding: 32px 16px 64px;
}
@media (min-width: 480px) { body { padding: 40px 24px 64px; } }
.container { max-width: 720px; margin: 0 auto; }

/* ── Animations ──────────────────────────── */
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}
.summary    { animation: fadeUp 0.4s ease both; }
.rules-card { animation: fadeUp 0.4s ease 0.06s both; }
.table-wrap { animation: fadeUp 0.4s ease 0.12s both; }

/* ── Page header ─────────────────────────── */
.page-eyebrow {
  display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;
}
.eyebrow-label {
  font-size: 11px; font-weight: 600; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--text-3);
}
.eyebrow-date { font-family: "DM Mono", monospace; font-size: 11px; color: var(--text-3); }
.page-title {
  font-family: "Instrument Serif", Georgia, serif;
  font-style: italic;
  font-size: clamp(28px, 7vw, 40px);
  font-weight: 400; letter-spacing: -0.01em;
  color: var(--text); line-height: 1.1; margin-bottom: 16px;
}

/* ── Badges ──────────────────────────────── */
.badges { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 32px; }
.badge {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 12px; border-radius: 20px; font-size: 12px;
  font-weight: 500; letter-spacing: 0.01em; border: 1px solid;
}
.badge-red    { color: var(--red);   background: rgba(255,69,58,0.10);  border-color: rgba(255,69,58,0.22); }
.badge-green  { color: var(--green); background: rgba(52,199,89,0.10);  border-color: rgba(52,199,89,0.22); }
.badge-blue   { color: var(--blue);  background: rgba(10,132,255,0.10); border-color: rgba(10,132,255,0.22); }
.badge-subtle { color: var(--text-2); background: var(--surface-2); border-color: var(--border); }
.badge-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; flex-shrink: 0; }

/* ── Summary card ────────────────────────── */
.summary {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--r12); overflow: hidden; margin-bottom: 32px;
}
.summary-hero {
  padding: 20px; display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px 0;
  border-bottom: 1px solid var(--border-2);
}
@media (min-width: 480px) {
  .summary-hero {
    grid-template-columns: 1.2fr 1fr 1fr;
    padding: 24px; gap: 0;
  }
  .summary-hero .stat + .stat { border-left: 1px solid var(--border-2); padding-left: 20px; }
}
.stat-label {
  font-size: 10px; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--text-3); margin-bottom: 6px;
}
.stat-value {
  font-family: "DM Mono", monospace; font-size: 22px; font-weight: 500;
  letter-spacing: -0.02em; color: var(--text); line-height: 1; margin-bottom: 4px;
}
.stat-note { font-size: 11px; color: var(--text-2); line-height: 1.55; margin-top: 6px; }

/* ── Rules card ──────────────────────────── */
.rules-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--r12); overflow: hidden; margin-bottom: 10px;
}
.rules-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 0;
}
@media (min-width: 480px) { .rules-grid { grid-template-columns: 1fr 1fr 1fr 1fr; } }
.rule-item {
  padding: 16px; border-right: 1px solid var(--border-2);
}
.rule-item:last-child { border-right: none; }
.rule-label {
  font-size: 10px; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--text-3); margin-bottom: 6px;
}
.rule-value {
  font-family: "DM Mono", monospace; font-size: 18px; font-weight: 500;
  color: var(--text); line-height: 1; margin-bottom: 6px;
}
.rule-note { font-size: 11px; color: var(--text-2); line-height: 1.5; }

/* ── Section divider ─────────────────────── */
.section-header { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.section-label {
  font-size: 10px; font-weight: 600; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--text-3); white-space: nowrap;
}
.section-rule { flex: 1; height: 1px; background: var(--border-2); }

/* ── Table ───────────────────────────────── */
.table-wrap {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--r12); overflow: hidden; margin-bottom: 10px;
  overflow-x: auto;
}
.pool-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.pool-table th {
  background: var(--surface-2); color: var(--text-3);
  padding: 10px 14px; text-align: left; font-size: 10px;
  font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
  border-bottom: 1px solid var(--border);
}
.pool-table td { padding: 10px 14px; border-bottom: 1px solid var(--border-2); }
.pool-table tr:last-child td { border-bottom: none; }
.pool-table tr:hover td { background: var(--surface-2); }
.version-current td { background: rgba(52,199,89,0.04); }

.ticker-chip {
  font-family: "DM Mono", monospace; font-size: 12px; font-weight: 500;
  letter-spacing: 0.04em; color: var(--text);
  background: var(--surface-2); padding: 3px 8px;
  border-radius: var(--r4); border: 1px solid var(--border); white-space: nowrap;
}
.market-chip {
  font-family: "DM Mono", monospace; font-size: 10px; font-weight: 600;
  letter-spacing: 0.06em; color: var(--text-3);
  background: var(--surface-2); padding: 2px 6px; border-radius: var(--r4);
}
.name-cell { color: var(--text-2); max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.empty-state { text-align: center; color: var(--text-3); font-size: 14px; padding: 48px 0; }
</style>"""
