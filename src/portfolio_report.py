"""Generate dark-Apple HTML risk report from a RiskReport."""
from html import escape as _e
from src.portfolio_risk import RiskReport, RiskAlert

_DIM_NAMES = {
    1: "方向性敞口（Dollar Delta）",
    2: "时间价值衰减（Theta）",
    3: "IV 敏感度（Vega）",
    4: "保证金安全边际",
    5: "集中度风险",
    6: "财报日在仓风险",
    7: "期权到期风险（DTE + Moneyness）",
    8: "Sell Put 安全垫",
    9: "Gamma 临近到期警告",
    10: "压力测试（大盘 -10%/-20%）",
}

_LEVEL_COLOR = {"red": "#ff453a", "yellow": "#ffd60a"}
_LEVEL_EMOJI = {"red": "🔴", "yellow": "🟡"}


def _alert_card(alert: RiskAlert) -> str:
    color = _LEVEL_COLOR.get(alert.level, "#ffd60a")
    emoji = _LEVEL_EMOJI.get(alert.level, "⚠️")
    dim_name = _DIM_NAMES.get(alert.dimension, f"维度 {alert.dimension}")
    options_html = "".join(f"<li>{_e(opt)}</li>" for opt in alert.options)
    ai_html = ""
    if alert.ai_suggestion:
        ai_html = f'<div class="ai-box">💡 AI 建议：{_e(alert.ai_suggestion)}</div>'
    return f"""
<div class="alert-card">
  <div class="alert-header" style="border-left: 4px solid {color}; color: {color};">
    {emoji} {_e(dim_name)} — {_e(alert.ticker)}
  </div>
  <div class="alert-detail">{_e(alert.detail)}</div>
  <ul class="options-list">{options_html}</ul>
  {ai_html}
</div>"""


def generate_html_report(report: RiskReport) -> str:
    red_count = sum(1 for a in report.alerts if a.level == "red")
    yellow_count = sum(1 for a in report.alerts if a.level == "yellow")
    cards_html = "\n".join(_alert_card(a) for a in report.alerts)
    pnl_color = "#30d158" if report.total_pnl >= 0 else "#ff453a"
    cushion_pct = f"{report.cushion * 100:.1f}%"
    stress = report.summary_stats.get("stress_test", {})
    drop_10 = stress.get("drop_10pct", 0)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Portfolio Risk Report — {_e(report.account_id)} {_e(report.report_date)}</title>
<style>
  :root {{
    --bg: #1c1c1e; --card: #2c2c2e; --text: #f5f5f7; --subtext: #98989d;
    --accent: #0a84ff; --red: #ff453a; --yellow: #ffd60a; --green: #30d158;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif; padding: 24px; }}
  .summary {{ background: var(--card); border-radius: 12px; padding: 20px; margin-bottom: 24px; display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; }}
  .stat-label {{ color: var(--subtext); font-size: 12px; margin-bottom: 4px; }}
  .stat-value {{ font-size: 20px; font-weight: 600; }}
  .alert-card {{ background: var(--card); border-radius: 12px; padding: 16px; margin-bottom: 16px; }}
  .alert-header {{ font-size: 15px; font-weight: 600; padding-left: 10px; margin-bottom: 10px; }}
  .alert-detail {{ color: var(--subtext); font-size: 13px; margin-bottom: 12px; }}
  .options-list {{ list-style: none; padding: 0; }}
  .options-list li {{ padding: 4px 0; font-size: 13px; color: var(--text); }}
  .ai-box {{ margin-top: 12px; background: rgba(10,132,255,0.12); border-radius: 8px; padding: 10px; font-size: 13px; color: var(--subtext); }}
  h1 {{ font-size: 22px; font-weight: 700; margin-bottom: 16px; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; margin-left: 6px; }}
</style>
</head>
<body>
<h1>Portfolio Risk Report
  <span class="badge" style="background:#ff453a22;color:#ff453a">{red_count} 红色</span>
  <span class="badge" style="background:#ffd60a22;color:#ffd60a">{yellow_count} 黄色</span>
</h1>
<div class="summary">
  <div><div class="stat-label">账户</div><div class="stat-value">{_e(report.account_id)}</div></div>
  <div><div class="stat-label">报告日期</div><div class="stat-value">{_e(report.report_date)}</div></div>
  <div><div class="stat-label">净资产 (NLV)</div><div class="stat-value">${report.net_liquidation:,.0f}</div></div>
  <div><div class="stat-label">未实现盈亏</div><div class="stat-value" style="color:{pnl_color}">${report.total_pnl:+,.0f}</div></div>
  <div><div class="stat-label">保证金缓冲</div><div class="stat-value">{cushion_pct}</div></div>
  <div><div class="stat-label">跌10%预估亏损</div><div class="stat-value" style="color:#ff453a">${drop_10:,.0f}</div></div>
</div>
{cards_html if cards_html else '<p style="color:var(--subtext);text-align:center;padding:40px">暂无风险预警</p>'}
</body>
</html>"""
