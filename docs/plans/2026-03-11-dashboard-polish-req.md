# Dashboard Card Polish — Requirements

> **Status:** Approved, ready for implementation
> **Date:** 2026-03-11

## 问题背景

基于用户反馈的 4 个视觉/交互问题，涉及股息卡片的可读性、策略选择器交互、内容溢出和整体密度。

---

## 1. 小标题亮度（dc-group-title）

**问题：** `.dc-group-title { color: var(--text-2) }` = rgba(236,236,236,0.60)，在深色背景下不够清晰。

**修复：** 将颜色提升至 `rgba(236,236,236,0.85)`（仅针对 `.dc-group-title`，其他 text-2 用法不变）。

```css
.dc-group-title {
  color: rgba(236,236,236,0.85);
  /* 其余不变 */
}
```

---

## 2. 策略选项卡交互 Bug

### 2.1 onclick 双引号 Bug

**问题：** Sell Put 标签的 `onclick` 属性在双引号 HTML 属性中使用了双引号：

```html
<!-- 当前（错误）-->
<span onclick="switchStrategyTab("AAPL","sell_put",this)">

<!-- 浏览器解析为（截断）-->
<span onclick="switchStrategyTab(">
```

**修复：** 统一使用单引号（与现货标签一致）：

```javascript
// buildStrategySection 中
(hasOption ? 'switchStrategyTab(\'' + ticker + '\',\'sell_put\',this)' : '')
```

### 2.2 旧信号无推荐策略/原因

**问题：** 历史信号的 payload 不含 `recommended_strategy`/`recommended_reason` 字段，导致 AI 推荐区块为空。

**修复：** 增加规则兜底文案：

```javascript
// 无 recommended_reason 时，根据 rec 显示默认文案
var recReason = p.recommended_reason
  || (rec === 'sell_put' ? 'Sell Put 综合年化显著高于现货股息率' : '现货持仓吃股息，策略稳健')
  || '';
```

### 2.3 HK/CN 无期权时 Sell Put 标签可点击

**现状：** HK/CN 使用 `disabled` 类（`pointer-events: none`），tooltip 无法触发。

**修复：** 新增 `.strategy-tab.disabled-reason` 样式（有 opacity 但保留点击）：

```css
.strategy-tab.disabled-reason {
  opacity: 0.45; cursor: pointer;
}
```

并在 HK/CN 时使用该类（而非 `disabled`）：

```javascript
var tabSellPutClass = !isUS ? 'disabled-reason' : (illiquid ? 'disabled-reason' : (hasOption ? '' : 'disabled'));
```

---

## 3. 展开箭头可见性 & 内容不溢出

### 3.1 `›` 箭头对比度低

**问题：** `.toggle-arrow { color: var(--text-2) }` = 60% 白色，加上字号 `font-weight: 300` 在右侧难以发现。

**修复：**

```css
.toggle-arrow {
  font-size: 20px; font-weight: 400; color: var(--text);  /* 改为全亮白 */
  opacity: 0.70;  /* 适当柔化，仍比 text-2 明显 */
}
```

### 3.2 analysis-toggle 负边距溢出

**问题：** `.analysis-toggle { margin: 0 -8px; padding: 5px 8px }` 在窄屏可能右侧溢出卡片内边距。

**修复：** 去掉负边距，改用圆角背景方式实现 hover 效果：

```css
.analysis-toggle {
  margin: 0;         /* 去掉 margin: 0 -8px */
  border-radius: var(--r8);
}
```

---

## 4. 卡片密度与字体大小

**问题：** 卡片垂直方向留白过多，文字偏小，信息密度低。用户反馈"卡片大，字小"。

### 4.1 字体大小调整

| 元素 | 当前 | 调整后 |
|------|------|--------|
| `.row-label` | 12px | 13px |
| `.row-value` | 13px | 14px |
| `.dc-body` (分析文本) | 13px | 13px（不变）|
| `.strategy-row-label` | 12px | 12px（不变）|
| `.strategy-row-value` | 13px | 13px（不变）|

### 4.2 行高/内边距压缩

```css
/* card-body：减少顶部内边距 */
.card-body { padding: 0 16px 10px; }      /* 原 2px 16px 12px */

/* card-row：减少行高 */
.card-row  { padding: 6px 0; min-height: 32px; }  /* 原 8px 0; 36px */

/* dc-group：减少组间距 */
.dc-group  { padding-bottom: 6px; margin-bottom: 1px; }  /* 原 8px/2px */
.dc-group-title { padding: 8px 0 5px; }   /* 原 10px 0 7px */
```

### 4.3 卡片头部微调

```css
.card-head { padding: 10px 16px; }  /* 原 12px 16px */
```

### 4.4 最大宽度

当前 `max-width: 760px`，保持不变。单列布局适合信息密度高的卡片。

---

## 文件变更

| 文件 | 变更 |
|------|------|
| `agent/static/dashboard.html` | CSS token 更新 + JS onclick 修复 + 兜底推荐文案 |

所有改动均在同一文件内完成，无后端变更。
