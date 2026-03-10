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

# Alert accent colors
_LEVEL_COLOR  = {"red": "#ff453a", "yellow": "#ffb340"}
_LEVEL_BG     = {"red": "rgba(255,69,58,0.10)",  "yellow": "rgba(255,179,64,0.09)"}
_LEVEL_BORDER = {"red": "rgba(255,69,58,0.22)",  "yellow": "rgba(255,179,64,0.20)"}

_OPT_LABELS = ["A", "B", "C", "D"]


def _options_rows(options: list, dim: int) -> str:
    pros_cons = _DIM_OPTIONS_PROS_CONS.get(dim, [])
    rows = ""
    for i, opt in enumerate(options):
        label  = _OPT_LABELS[i] if i < len(_OPT_LABELS) else str(i + 1)
        pc     = pros_cons[i] if i < len(pros_cons) else ("", "")
        action = opt[3:] if opt.startswith(f"{label}. ") else opt
        pro_html = f'<span class="opt-pro">↑ {_e(pc[0])}</span>' if pc[0] else ""
        con_html = f'<span class="opt-con">↓ {_e(pc[1])}</span>' if pc[1] else ""
        sep = ' class="opt-row opt-row--sep"' if i > 0 else ' class="opt-row"'
        rows += f"""
<div{sep}>
  <div class="opt-pill">{label}</div>
  <div class="opt-body">
    <div class="opt-action">{_e(action)}</div>
    <div class="opt-procon">{pro_html}{con_html}</div>
  </div>
</div>"""
    return rows


def _alert_card(alert: RiskAlert) -> str:
    color      = _LEVEL_COLOR.get(alert.level,  "#ffb340")
    bg         = _LEVEL_BG.get(alert.level,     "rgba(255,179,64,0.09)")
    border_col = _LEVEL_BORDER.get(alert.level, "rgba(255,179,64,0.20)")
    dim_name   = _DIM_NAMES.get(alert.dimension, f"维度 {alert.dimension}")
    plain      = _DIM_PLAIN.get(alert.dimension, "")
    opts_html  = _options_rows(alert.options, alert.dimension) if alert.options else ""
    ai_html    = ""
    if alert.ai_suggestion:
        ai_html = f"""
<div class="ai-box">
  <span class="ai-label">AI 建议</span>
  {_e(alert.ai_suggestion)}
</div>"""
    plain_html = f'<p class="plain-desc">{_e(plain)}</p>' if plain else ""
    opts_block = (f'<div class="options-section">'
                  f'<div class="options-title">处理方法</div>{opts_html}</div>') if opts_html else ""
    return f"""
<div class="alert-card" style="border-color:{border_col}">
  <div class="card-head" style="background:{bg};border-bottom:1px solid {border_col}">
    <div class="card-left">
      <span class="level-dot" style="background:{color}"></span>
      <span class="card-dim-name">{_e(dim_name)}</span>
    </div>
    <span class="card-ticker" style="color:{color};border-color:{border_col}">{_e(alert.ticker)}</span>
  </div>
  <div class="card-body">
    {plain_html}
    <p class="tech-detail">{_e(alert.detail)}</p>
    {opts_block}
    {ai_html}
  </div>
</div>"""


def generate_html_report(report: RiskReport) -> str:
    red_count    = sum(1 for a in report.alerts if a.level == "red")
    yellow_count = sum(1 for a in report.alerts if a.level == "yellow")
    cards_html   = "\n".join(_alert_card(a) for a in report.alerts)
    pnl_color    = "#34c759" if report.total_pnl >= 0 else "#ff453a"
    cushion_val  = report.cushion * 100
    cushion_color  = "#ff453a" if cushion_val < 10 else ("#ffb340" if cushion_val < 25 else "#34c759")
    cushion_label  = "危险" if cushion_val < 10 else ("注意" if cushion_val < 25 else "安全")
    cushion_bar_w  = min(cushion_val / 40 * 100, 100)
    stress   = report.summary_stats.get("stress_test", {})
    drop_10  = stress.get("drop_10pct", 0)
    alert_section = cards_html if cards_html else '<p class="empty-state">暂无风险预警 ✓</p>'
    acct_name = _e(report.account_id) if report.account_id else "Portfolio"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>风险报告 · {acct_name} · {_e(report.report_date)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=DM+Sans:opsz,wght@9..40,300..600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
/* ── Reset ───────────────────────────────── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

/* ── Tokens (8px grid, per spec) ─────────── */
:root {{
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
}}

/* ── Base ────────────────────────────────── */
body {{
  background: var(--bg);
  color: var(--text);
  font-family: "DM Sans", -apple-system, "Helvetica Neue", sans-serif;
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  min-height: 100vh;
  padding: 32px 16px 64px;
}}
@media (min-width: 480px) {{ body {{ padding: 40px 24px 64px; }} }}

.container {{ max-width: 720px; margin: 0 auto; }}

/* ── Animations ──────────────────────────── */
@keyframes fadeUp {{
  from {{ opacity: 0; transform: translateY(12px); }}
  to   {{ opacity: 1; transform: translateY(0); }}
}}
@keyframes barGrow {{
  from {{ width: 0; }}
}}

.summary     {{ animation: fadeUp 0.4s ease both; }}
.alert-card  {{ animation: fadeUp 0.4s ease both; }}
.alert-card:nth-child(1)  {{ animation-delay: 0.06s; }}
.alert-card:nth-child(2)  {{ animation-delay: 0.12s; }}
.alert-card:nth-child(3)  {{ animation-delay: 0.18s; }}
.alert-card:nth-child(4)  {{ animation-delay: 0.24s; }}
.alert-card:nth-child(5)  {{ animation-delay: 0.30s; }}
.alert-card:nth-child(6)  {{ animation-delay: 0.36s; }}
.alert-card:nth-child(n+7){{ animation-delay: 0.40s; }}

/* ── Page header ─────────────────────────── */
.page-eyebrow {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}}
.eyebrow-label {{
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-3);
}}
.eyebrow-date {{
  font-family: "DM Mono", monospace;
  font-size: 11px;
  color: var(--text-3);
}}

.page-title {{
  font-family: "Instrument Serif", Georgia, serif;
  font-style: italic;
  font-size: clamp(28px, 7vw, 40px);
  font-weight: 400;
  letter-spacing: -0.01em;
  color: var(--text);
  line-height: 1.1;
  margin-bottom: 16px;
}}

.badges {{
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 32px;
}}
.badge {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.01em;
  border: 1px solid;
}}
.badge-red    {{ color: var(--red);   background: rgba(255,69,58,0.10);  border-color: rgba(255,69,58,0.22); }}
.badge-yellow {{ color: var(--amber); background: rgba(255,179,64,0.10); border-color: rgba(255,179,64,0.22); }}
.badge-dot {{ width: 6px; height: 6px; border-radius: 50%; background: currentColor; flex-shrink: 0; }}

/* ── Summary card ────────────────────────── */
.summary {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r12);
  overflow: hidden;
  margin-bottom: 32px;
}}

.summary-hero {{
  padding: 20px 20px 0;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 20px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--border-2);
}}
@media (min-width: 480px) {{
  .summary-hero {{ grid-template-columns: 1.4fr 1fr 1fr; padding: 24px 24px 20px; gap: 0; }}
  .summary-hero .stat + .stat {{ border-left: 1px solid var(--border-2); padding-left: 20px; }}
}}

.summary-foot {{
  padding: 20px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px 0;
}}
@media (min-width: 480px) {{
  .summary-foot {{
    padding: 20px 24px 24px;
    gap: 0;
  }}
  .summary-foot .stat + .stat {{ border-left: 1px solid var(--border-2); padding-left: 20px; }}
}}

.stat-label {{
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-3);
  margin-bottom: 6px;
}}
.stat-value {{
  font-family: "DM Mono", monospace;
  font-size: 22px;
  font-weight: 500;
  letter-spacing: -0.02em;
  color: var(--text);
  line-height: 1;
  margin-bottom: 4px;
}}
.stat-value--hero {{
  font-size: clamp(22px, 5vw, 30px);
}}
.stat-note {{
  font-size: 11px;
  color: var(--text-2);
  line-height: 1.55;
  margin-top: 6px;
}}

/* Cushion segments */
.cushion-track {{
  display: flex;
  gap: 3px;
  margin-top: 10px;
  margin-bottom: 4px;
}}
.cushion-seg {{
  height: 3px;
  border-radius: 2px;
  flex: 1;
  background: var(--border);
  transition: background 0.6s ease;
}}
.cushion-label {{
  font-size: 11px;
  font-weight: 600;
  color: var(--text-3);
  margin-top: 2px;
}}

/* ── Section divider ─────────────────────── */
.section-header {{
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}}
.section-label {{
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-3);
  white-space: nowrap;
}}
.section-rule {{
  flex: 1;
  height: 1px;
  background: var(--border-2);
}}

/* ── Alert card ──────────────────────────── */
.alert-card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r12);
  overflow: hidden;
  margin-bottom: 10px;
  transition: border-color 0.2s;
}}
.alert-card:hover {{ border-color: rgba(255,255,255,0.14); }}

.card-head {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  gap: 12px;
}}
.card-left {{
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}}
.level-dot {{
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}}
.card-dim-name {{
  font-size: 13px;
  font-weight: 600;
  letter-spacing: -0.01em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}
.card-ticker {{
  font-family: "DM Mono", monospace;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.06em;
  padding: 3px 8px;
  border-radius: var(--r4);
  border: 1px solid;
  background: rgba(0,0,0,0.3);
  white-space: nowrap;
  flex-shrink: 0;
}}

.card-body {{ padding: 0 16px 16px; }}

.plain-desc {{
  font-size: 14px;
  color: var(--text-2);
  line-height: 1.65;
  padding: 12px 0 10px;
  border-bottom: 1px solid var(--border-2);
  margin-bottom: 10px;
}}

.tech-detail {{
  font-family: "DM Mono", monospace;
  font-size: 11px;
  color: var(--text-3);
  background: var(--surface-2);
  display: inline-block;
  padding: 4px 8px;
  border-radius: var(--r4);
  margin-bottom: 12px;
  letter-spacing: 0.01em;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}}

/* ── Options ─────────────────────────────── */
.options-section {{ padding-top: 2px; }}
.options-title {{
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-3);
  margin-bottom: 8px;
}}

.opt-row {{
  display: flex;
  align-items: flex-start;
  padding: 8px 0;
  gap: 10px;
}}
.opt-row--sep {{ border-top: 1px solid var(--border-2); }}

.opt-pill {{
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text-3);
  font-size: 10px;
  font-weight: 600;
  font-family: "DM Mono", monospace;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 2px;
}}
.opt-body {{ flex: 1; min-width: 0; }}
.opt-action {{
  font-size: 13px;
  color: var(--text);
  line-height: 1.5;
  margin-bottom: 4px;
}}
.opt-procon {{
  display: flex;
  flex-direction: column;
  gap: 1px;
}}
.opt-pro {{
  font-size: 11px;
  color: var(--green);
  line-height: 1.5;
}}
.opt-con {{
  font-size: 11px;
  color: var(--text-2);
  line-height: 1.5;
}}

/* ── AI box ──────────────────────────────── */
.ai-box {{
  margin-top: 12px;
  background: rgba(10,132,255,0.06);
  border: 1px solid rgba(10,132,255,0.16);
  border-radius: var(--r8);
  padding: 10px 12px;
  font-size: 13px;
  color: var(--text-2);
  line-height: 1.65;
}}
.ai-label {{
  display: block;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--blue);
  margin-bottom: 5px;
}}

.empty-state {{
  text-align: center;
  color: var(--text-3);
  font-size: 14px;
  padding: 48px 0;
}}
</style>
</head>
<body>
<div class="container">

<div class="page-eyebrow">
  <span class="eyebrow-label">Portfolio Risk Report</span>
  <span class="eyebrow-date">{_e(report.report_date)}</span>
</div>
<h1 class="page-title">{acct_name}</h1>
<div class="badges">
  <span class="badge badge-red"><span class="badge-dot"></span>{red_count} 红色预警</span>
  <span class="badge badge-yellow"><span class="badge-dot"></span>{yellow_count} 黄色提示</span>
</div>

<div class="summary">
  <div class="summary-hero">
    <div class="stat">
      <div class="stat-label">净资产 NLV</div>
      <div class="stat-value stat-value--hero">${report.net_liquidation:,.0f}</div>
    </div>
    <div class="stat">
      <div class="stat-label">未实现盈亏</div>
      <div class="stat-value" style="color:{pnl_color}">${report.total_pnl:+,.0f}</div>
    </div>
    <div class="stat">
      <div class="stat-label">报告日期</div>
      <div class="stat-value" style="font-size:16px;letter-spacing:0">{_e(report.report_date)}</div>
    </div>
  </div>
  <div class="summary-foot">
    <div class="stat">
      <div class="stat-label">保证金缓冲</div>
      <div class="stat-value" style="color:{cushion_color}">{cushion_val:.1f}%</div>
      <div class="cushion-track" id="ctrack"></div>
      <div class="cushion-label" style="color:{cushion_color}">{cushion_label}</div>
      <div class="stat-note">可用资金超出维持保证金的部分<br>&gt;25% 安全 · &lt;10% 危险</div>
    </div>
    <div class="stat">
      <div class="stat-label">大盘跌10%预估亏损</div>
      <div class="stat-value" style="color:var(--red)">${drop_10:,.0f}</div>
      <div class="stat-note">假设 SPY 跌10%<br>按各仓位市值 × Beta 估算</div>
    </div>
  </div>
</div>

<div class="section-header">
  <span class="section-label">风险预警</span>
  <div class="section-rule"></div>
  <span class="section-label">{red_count + yellow_count} 条</span>
</div>
{alert_section}

</div>
<script>
(function() {{
  // Cushion track — 10 segments, fill coloured ones
  var val = {cushion_val:.2f};
  var color = "{cushion_color}";
  var track = document.getElementById("ctrack");
  var total = 10;
  var filled = Math.round(Math.min(val / 40, 1) * total);
  for (var i = 0; i < total; i++) {{
    var seg = document.createElement("div");
    seg.className = "cushion-seg";
    if (i < filled) {{
      seg.style.background = color;
      seg.style.opacity = 0.8 - i * 0.04;
    }}
    track.appendChild(seg);
  }}
}})();
</script>
</body>
</html>"""
