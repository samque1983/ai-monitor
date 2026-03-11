/**
 * Test: strategy tab switching in dashboard.html
 * Pure Node.js — minimal DOM mock, no external dependencies.
 */
const fs = require('fs');
const path = require('path');

// ── Minimal DOM mock ─────────────────────────────────────────────────────────
class ClassList {
  constructor(init) { this._s = new Set(init || []); }
  add(...c)    { c.forEach(x => this._s.add(x)); }
  remove(...c) { c.forEach(x => this._s.delete(x)); }
  contains(c)  { return this._s.has(c); }
  toggle(c, force) {
    if (force === true)       this._s.add(c);
    else if (force === false) this._s.delete(c);
    else this._s.has(c) ? this._s.delete(c) : this._s.add(c);
  }
}

class MockEl {
  constructor({ id, classes, dataset, parent } = {}) {
    this.id = id || '';
    this.classList = new ClassList(classes || []);
    this.dataset = dataset || {};
    this._parent = parent || null;
    this._children = [];
    if (parent) parent._children.push(this);
  }
  closest(selector) {
    const cls = selector.replace(/^\./, '');
    let node = this;
    while (node) {
      if (node.classList.contains(cls)) return node;
      node = node._parent;
    }
    return null;
  }
  querySelectorAll(selector) {
    const cls = selector.replace(/^\./, '');
    const out = [];
    (function walk(el) {
      el._children.forEach(c => { if (c.classList.contains(cls)) out.push(c); walk(c); });
    })(this);
    return out;
  }
  // Support querySelectorAll on dc-group to find panels by class
  // (already handled above — .strategy-panel is a class)
}

// DOM registry
const byId = {};
function mkEl(opts) {
  const e = new MockEl(opts);
  if (e.id) byId[e.id] = e;
  return e;
}

// ── Exact copy of switchStrategyTab from dashboard.html ──────────────────────
function switchStrategyTab(ticker, strategy, tabEl) {
  var tabsContainer = tabEl.closest('.strategy-tabs');
  if (tabsContainer) {
    tabsContainer.querySelectorAll('.strategy-tab').forEach(function(t) {
      t.classList.remove('active', 'active-green');
    });
  }
  tabEl.classList.add(strategy === 'spot' ? 'active-green' : 'active');
  // Toggle panels via DOM traversal (matches new dashboard.html implementation)
  var group = tabEl.closest('.dc-group');
  if (group) {
    group.querySelectorAll('.strategy-panel').forEach(function(panel) {
      panel.classList.toggle('visible', panel.dataset.strategy === strategy);
    });
  }
}

// ── Test setup: build mock DOM for a ticker ──────────────────────────────────
function buildMockDOM(ticker, rec) {
  // <div class="dc-group">  (parent for closest() lookup)
  const group = mkEl({ classes: ['dc-group'] });

  // <div class="strategy-tabs" id="stabs-{ticker}">
  const tabsDiv = mkEl({ id: 'stabs-' + ticker, classes: ['strategy-tabs'], parent: group });

  // <span class="strategy-tab" data-ticker data-strategy="spot">
  const spotTab = mkEl({
    classes: ['strategy-tab'].concat(rec === 'spot' ? ['active-green'] : []),
    dataset: { ticker, strategy: 'spot' },
    parent: tabsDiv,
  });

  // <span class="strategy-tab" data-ticker data-strategy="sell_put">
  const spTab = mkEl({
    classes: ['strategy-tab'].concat(rec === 'sell_put' ? ['active'] : []),
    dataset: { ticker, strategy: 'sell_put' },
    parent: tabsDiv,
  });

  // Panels — now use data-strategy instead of id for lookup
  const spotPanel = mkEl({
    classes: rec === 'spot' ? ['strategy-panel', 'visible'] : ['strategy-panel'],
    dataset: { strategy: 'spot' },
    parent: group,
  });
  const spPanel = mkEl({
    classes: rec === 'sell_put' ? ['strategy-panel', 'visible'] : ['strategy-panel'],
    dataset: { strategy: 'sell_put' },
    parent: group,
  });

  return { group, tabsDiv, spotTab, spTab, spotPanel, spPanel };
}

// ── Assertions ───────────────────────────────────────────────────────────────
let pass = 0, fail = 0;
function ok(cond, msg) {
  if (cond) { console.log('  ✓', msg); pass++; }
  else       { console.error('  ✗', msg); fail++; }
}

// ── Test 1: AAPL — sell_put recommended, click 現貨 ──────────────────────────
console.log('\nTest 1: sell_put recommended → click 現貨 tab');
{
  const { spotTab, spTab, spotPanel, spPanel } = buildMockDOM('AAPL', 'sell_put');

  ok(!spotPanel.classList.contains('visible'), 'initial: spot panel hidden');
  ok( spPanel.classList.contains('visible'),   'initial: sell_put panel visible');
  ok(!spotTab.classList.contains('active-green'), 'initial: 現貨 tab not active');
  ok( spTab.classList.contains('active'),         'initial: Sell Put tab active');

  switchStrategyTab('AAPL', 'spot', spotTab);

  ok( spotPanel.classList.contains('visible'),    'after click 現貨: spot panel visible');
  ok(!spPanel.classList.contains('visible'),      'after click 現貨: sell_put panel hidden');
  ok( spotTab.classList.contains('active-green'), 'after click 現貨: 現貨 tab active-green');
  ok(!spTab.classList.contains('active'),         'after click 現貨: Sell Put tab not active');
}

// ── Test 2: AAPL — click Sell Put to switch back ─────────────────────────────
console.log('\nTest 2: after clicking 現貨, click Sell Put to switch back');
{
  // reuse the group from test 1 — grab panels by data-strategy
  const group   = byId['stabs-AAPL']._parent;
  const spotTab = byId['stabs-AAPL']._children[0];
  const spTab   = byId['stabs-AAPL']._children[1];
  const panels  = group.querySelectorAll('strategy-panel');
  // find via dataset
  const spotPanel = group._children.find(c => c.classList.contains('strategy-panel') && c.dataset.strategy === 'spot');
  const spPanel   = group._children.find(c => c.classList.contains('strategy-panel') && c.dataset.strategy === 'sell_put');

  switchStrategyTab('AAPL', 'sell_put', spTab);

  ok(!spotPanel.classList.contains('visible'), 'spot panel hidden');
  ok( spPanel.classList.contains('visible'),   'sell_put panel visible');
  ok( spTab.classList.contains('active'),      'Sell Put tab active');
  ok(!spotTab.classList.contains('active-green'), '現貨 tab not active');
}

// ── Test 3: MSFT — spot recommended, click Sell Put ──────────────────────────
console.log('\nTest 3: spot recommended → click Sell Put tab');
{
  const { spotTab, spTab, spotPanel, spPanel } = buildMockDOM('MSFT', 'spot');

  ok( spotPanel.classList.contains('visible'),    'initial: spot panel visible');
  ok(!spPanel.classList.contains('visible'),      'initial: sell_put panel hidden');

  switchStrategyTab('MSFT', 'sell_put', spTab);

  ok(!spotPanel.classList.contains('visible'),    'after click SP: spot panel hidden');
  ok( spPanel.classList.contains('visible'),      'after click SP: sell_put panel visible');
  ok( spTab.classList.contains('active'),         'Sell Put tab active');
}

// ── Test 4: closest() traversal works ────────────────────────────────────────
console.log('\nTest 4: closest() finds .strategy-tabs parent');
{
  const { spotTab, tabsDiv } = buildMockDOM('GOOG', 'sell_put');
  ok(spotTab.closest('.strategy-tabs') === tabsDiv, 'closest(".strategy-tabs") returns parent div');
}

// ── Summary ──────────────────────────────────────────────────────────────────
console.log(`\n${'─'.repeat(50)}`);
console.log(`Results: ${pass} passed, ${fail} failed`);
if (fail > 0) process.exit(1);
