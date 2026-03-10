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

# 一句话通俗解释，让不熟悉术语的人也能秒懂
_DIM_PLAIN = {
    1: "你的总持仓规模相对账户净资产偏大，市场每跌 1%，亏损就越明显。",
    2: "你整体是期权买方，每天光是时间流逝就在亏钱，需要有明确的短期催化剂支撑。",
    3: "你整体是期权卖方（空 Vega），一旦市场恐慌、波动率飙升，你的持仓会承压。",
    4: "账户保证金缓冲不足，市场一旦下跌，券商可能强制平仓你的仓位。",
    5: "某只股票在组合里占比过高，它一旦暴跌，会对整体资产造成严重冲击。",
    6: "你持有的期权到期日在财报发布之后，财报当天的跳空可能直接击穿安全垫。",
    7: "期权快到期了或者已经进入实值，被指派（强制买入股票）的风险很高，需尽快决定。",
    8: "这个 Sell Put 已经赚到了大部分权利金（>75%），继续持有的风险收益比已经不划算。",
    9: "期权快到期且 Gamma 很高，股价稍微一动盈亏就会剧烈变化，止损很难精准执行。",
    10: "如果大盘下跌 10%，你的组合预估亏损超过净资产的 10%，整体下行保护不足。",
}

# 每个维度的选项利弊，与 portfolio_risk.py 中 options 列表顺序对应（A/B/C/D）
_DIM_OPTIONS_PROS_CONS = {
    1: [
        ("直接降低方向风险，效果最快", "可能踏空后续上涨，卖出时机难把握"),
        ("保留持仓不变，控制下行风险", "需持续支付权利金，长期拖累收益"),
        ("降低 Delta 同时收取权利金", "股价大涨时仓位会被 Call 走，限制上行"),
        ("无摩擦成本，看多时可能受益", "下行时亏损随杠杆放大，风险持续存在"),
    ],
    2: [
        ("止住每日时间损耗，确定性止血", "若行情随后爆发，会错失全部收益"),
        ("若判断准确，潜在收益可观", "时间持续消耗，亏损每天叠加"),
        ("降低 Theta 成本，同时保留方向性", "同时限制了最大盈利空间"),
        ("无需操作，等待波动", "每日 Theta 是确定性支出，无催化剂时纯粹亏损"),
    ],
    3: [
        ("直接降低 Vega 敞口，立竿见影", "需支付权利金买回，压缩已有利润"),
        ("无需平仓原有仓位，灵活", "VIX 工具成本高且滑点大"),
        ("零成本，IV 高时买回更划算", "IV 若继续上升，亏损持续扩大"),
        ("Theta 收益可能覆盖 Vega 亏损", "需精确计算两者平衡，判断难度高"),
    ],
    4: [
        ("最快释放保证金，立竿见影", "可能在最差时点被迫离场，踩在低点"),
        ("不改变任何仓位", "需要额外资金，不一定随时可用"),
        ("大幅降低保证金占用", "需支付买入 Put 权利金，减少最大收益"),
        ("无操作成本", "期间若市场下跌，可能被强制平仓，更被动"),
    ],
    5: [
        ("降低单股风险，改善分散度", "若该股后续大涨，减仓会带来遗憾"),
        ("持仓不变，控制尾部风险", "长期持有 Put 成本较高"),
        ("零成本，保留上行空间", "止损执行时可能有滑点，且需纪律执行"),
        ("若长期看好该股，高仓位合理", "单股暴雷将对整体组合造成重大冲击"),
    ],
    6: [
        ("彻底消除财报风险，锁定收益", "若财报平稳，白白让出剩余权利金"),
        ("保留卖方收益，规避财报风险", "需支付 Roll 成本，权利金可能减少"),
        ("扩大安全垫，应对财报跳空", "行权价降低意味着权利金同步减少"),
        ("若判断正确，全收权利金", "财报跳空可能造成大幅亏损甚至被指派"),
    ],
    7: [
        ("确定性止损，控制最大亏损", "若之后出现反弹，会后悔提前平仓"),
        ("以行权价承接股票，可等待回升", "占用大量资金，股票可能继续下跌"),
        ("争取时间等待反弹", "需支付 Roll 成本，亏损有可能继续扩大"),
        ("若反弹则可减少亏损", "时间极短，不确定性极高，赌博成分大"),
    ],
    8: [
        ("确定实现已有收益，释放保证金", "放弃剩余权利金（通常不超过 25%）"),
        ("获取全部权利金，最大化收益", "若行情反转，已实现的大部分收益可能回吐"),
        ("增加安全垫，同时可能增加权利金", "需支付 Roll 成本和时间"),
        ("保留收益可能性，有止损保护", "止损线需设置精准，执行时有滑点风险"),
    ],
    9: [
        ("保留部分收益，降低非线性风险", "减少了 Theta 收入来源"),
        ("彻底消除 Gamma 风险", "放弃所有剩余权利金"),
        ("限制最大亏损，保留 Theta 收益", "需支付买入 Put 权利金"),
        ("若安全垫充足，收益最大", "Gamma 加速变化，止损难以精准执行"),
    ],
    10: [
        ("直接对冲系统性风险，效果确定", "对冲成本较高，持续拖累整体收益"),
        ("从根本上降低组合波动率", "可能在市场反弹时跑输大盘"),
        ("限制极端亏损，同时降低保证金", "限制了最大收益空间"),
        ("若市场未大跌，收益不受影响", "系统性下跌时亏损可能超出预期"),
    ],
}

_LEVEL_COLOR = {"red": "#ff453a", "yellow": "#ffd60a"}
_LEVEL_EMOJI = {"red": "🔴", "yellow": "🟡"}


def _options_table(options: list, dim: int) -> str:
    """Render options as a table with pro/con columns."""
    pros_cons = _DIM_OPTIONS_PROS_CONS.get(dim, [])
    rows = ""
    for i, opt in enumerate(options):
        pc = pros_cons[i] if i < len(pros_cons) else ("", "")
        pro_html = f'<span class="pro">✅ {_e(pc[0])}</span>' if pc[0] else ""
        con_html = f'<span class="con">❌ {_e(pc[1])}</span>' if pc[1] else ""
        rows += f"""
  <tr>
    <td class="opt-label">{_e(opt)}</td>
    <td class="opt-pc">{pro_html}{con_html}</td>
  </tr>"""
    return f'<table class="options-table"><tbody>{rows}</tbody></table>'


def _alert_card(alert: RiskAlert) -> str:
    color = _LEVEL_COLOR.get(alert.level, "#ffd60a")
    emoji = _LEVEL_EMOJI.get(alert.level, "⚠️")
    dim_name = _DIM_NAMES.get(alert.dimension, f"维度 {alert.dimension}")
    plain = _DIM_PLAIN.get(alert.dimension, "")
    plain_html = f'<div class="plain-desc">{_e(plain)}</div>' if plain else ""
    options_html = _options_table(alert.options, alert.dimension) if alert.options else ""
    ai_html = ""
    if alert.ai_suggestion:
        ai_html = f'<div class="ai-box">💡 AI 建议：{_e(alert.ai_suggestion)}</div>'
    return f"""
<div class="alert-card">
  <div class="alert-header" style="border-left: 4px solid {color}; color: {color};">
    {emoji} {_e(dim_name)} — {_e(alert.ticker)}
  </div>
  {plain_html}
  <div class="alert-detail">{_e(alert.detail)}</div>
  {options_html}
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
  .alert-header {{ font-size: 15px; font-weight: 600; padding-left: 10px; margin-bottom: 8px; }}
  .plain-desc {{ font-size: 13px; color: var(--text); background: rgba(255,255,255,0.05); border-radius: 6px; padding: 8px 10px; margin-bottom: 10px; line-height: 1.5; }}
  .alert-detail {{ color: var(--subtext); font-size: 12px; margin-bottom: 12px; font-family: monospace; }}
  .options-table {{ width: 100%; border-collapse: collapse; margin-top: 4px; }}
  .options-table tr {{ border-top: 1px solid rgba(255,255,255,0.06); }}
  .opt-label {{ font-size: 13px; color: var(--text); padding: 7px 8px 7px 0; vertical-align: top; width: 42%; }}
  .opt-pc {{ font-size: 12px; padding: 7px 0; vertical-align: top; }}
  .pro {{ display: block; color: #30d158; line-height: 1.5; }}
  .con {{ display: block; color: #98989d; line-height: 1.5; }}
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
