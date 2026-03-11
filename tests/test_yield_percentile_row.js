/**
 * Test: yield percentile row rendering helpers.
 * Pure Node.js — no external dependencies.
 */

// ── Inline the helpers we'll implement in dashboard.html ─────────────────────
function buildPercentileBar(pct) {
  var filled = Math.round(pct / 10);
  var bar = '';
  for (var i = 0; i < 10; i++) bar += (i < filled ? '▰' : '░');
  return bar;
}

function renderYieldPercentileRow(p) {
  var pct     = p.yield_percentile;
  var p10     = p.yield_p10 != null ? p.yield_p10 : null;
  var p90     = p.yield_p90 != null ? p.yield_p90 : null;
  var histMax = p.yield_hist_max != null ? p.yield_hist_max : null;

  if (p10 == null || p90 == null) {
    return '<span class="row-label">历史分位</span>'
         + '<span class="row-value">' + pct + '%</span>';
  }

  var color = pct >= 70 ? 'var(--green)' : (pct < 30 ? 'var(--orange)' : 'inherit');
  var bar   = buildPercentileBar(pct);
  var range = p10.toFixed(1) + '–' + p90.toFixed(1) + '%';
  var tip   = histMax != null
    ? '历史最高 ' + histMax.toFixed(1) + '%（含黑天鹅期，已剔除极值计算分位）'
    : '';

  return '<span class="row-label">入场时机</span>'
       + '<span class="row-value" style="color:' + color + ';font-family:var(--mono)">'
       + bar + ' ' + pct + '%</span>'
       + '<span class="row-label" style="opacity:0.6"> (正常区间 ' + range + ')</span>'
       + (tip ? '<span class="info-icon" title="' + tip + '">ℹ</span>' : '');
}

// ── Assertions ────────────────────────────────────────────────────────────────
let pass = 0, fail = 0;
function ok(cond, msg) {
  if (cond) { console.log('  ✓', msg); pass++; }
  else       { console.error('  ✗', msg); fail++; }
}

console.log('\nTest 1: new format with p10/p90');
{
  var html = renderYieldPercentileRow({ yield_percentile: 82, yield_p10: 3.5, yield_p90: 5.8, yield_hist_max: 12.0 });
  ok(html.includes('入场时机'), 'label is 入场时机');
  ok(html.includes('▰'), 'progress bar present');
  ok(html.includes('82%'), 'percentile shown');
  ok(html.includes('3.5–5.8%'), 'range shown');
  ok(html.includes('12.0%'), 'hist_max in tooltip');
  ok(html.includes('var(--green)'), 'green color for high percentile');
}

console.log('\nTest 2: fallback for old signal (no p10/p90)');
{
  var html = renderYieldPercentileRow({ yield_percentile: 75, yield_p10: null, yield_p90: null });
  ok(html.includes('历史分位'), 'fallback label 历史分位');
  ok(!html.includes('▰'), 'no progress bar');
  ok(html.includes('75%'), 'percentile shown');
}

console.log('\nTest 3: low percentile gets orange color');
{
  var html = renderYieldPercentileRow({ yield_percentile: 20, yield_p10: 3.5, yield_p90: 5.8, yield_hist_max: null });
  ok(html.includes('var(--orange)'), 'orange for low percentile');
}

console.log('\nTest 4: progress bar fills correctly');
{
  ok(buildPercentileBar(82) === '▰▰▰▰▰▰▰▰░░', '82% → 8 filled');
  ok(buildPercentileBar(50) === '▰▰▰▰▰░░░░░', '50% → 5 filled');
  ok(buildPercentileBar(100) === '▰▰▰▰▰▰▰▰▰▰', '100% → 10 filled');
  ok(buildPercentileBar(0) === '░░░░░░░░░░',  '0% → 0 filled');
}

console.log(`\n${'─'.repeat(50)}`);
console.log(`Results: ${pass} passed, ${fail} failed`);
if (fail > 0) process.exit(1);
