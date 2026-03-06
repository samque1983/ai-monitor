#!/usr/bin/env python3
"""
高股息养老股池 — 命令行查看工具

用法:
    python scripts/view_dividend_pool.py              # 查看最新版本
    python scripts/view_dividend_pool.py --list       # 列出所有版本
    python scripts/view_dividend_pool.py --version monthly_2026-02
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config
from src.dividend_store import DividendStore


def main():
    parser = argparse.ArgumentParser(description="查看高股息养老股池")
    parser.add_argument("--list", action="store_true", help="列出所有历史版本")
    parser.add_argument("--version", type=str, help="查看指定版本 (e.g. monthly_2026-02)")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    db_path = config.get("data", {}).get("dividend_db_path", "data/dividend_pool.db")

    if not os.path.exists(db_path):
        print(f"数据库不存在: {db_path}")
        print("请先运行: python scripts/run_dividend_screening.py")
        sys.exit(1)

    store = DividendStore(db_path)

    try:
        if args.list:
            _print_versions(store)
        else:
            version = args.version
            if not version:
                versions = store.list_versions()
                if not versions:
                    print("池子为空，请先运行筛选脚本")
                    return
                version = versions[0]["version"]
            _print_pool(store, version)
    finally:
        store.close()


def _print_versions(store: DividendStore):
    versions = store.list_versions()
    if not versions:
        print("暂无历史版本")
        return
    print(f"\n{'版本':<22} {'筛选时间':<20} {'入池数':>6} {'平均评分':>8}")
    print("-" * 62)
    for v in versions:
        created = v.get("created_at", "")[:16].replace("T", " ")
        marker = " ← 当前" if v == versions[0] else ""
        print(f"{v['version']:<22} {created:<20} {v['tickers_count']:>6} {v['avg_quality_score']:>8.1f}{marker}")


def _print_pool(store: DividendStore, version: str):
    records = store.get_pool_by_version(version)
    if not records:
        print(f"版本 {version} 不存在或池子为空")
        return

    print(f"\n版本: {version} | 入池: {len(records)} 支标的\n")
    header = f"{'代码':<12} {'市场':<5} {'评分':>5} {'连续年':>6} {'股息率':>7} {'派息类型':<8} {'派息率':>7} {'行业'}"
    print(header)
    print("-" * 80)
    for r in records:
        yield_str = f"{r['dividend_yield']:.1f}%" if r.get('dividend_yield') else "N/A "
        payout_str = f"{r['payout_ratio']:.0f}%" if r.get('payout_ratio') else "N/A"
        score_str = f"{r['quality_score']:.0f}" if r.get('quality_score') else "N/A"
        ptype = r.get('payout_type') or 'GAAP'
        print(
            f"{r['ticker']:<12} {r.get('market',''):<5} {score_str:>5} "
            f"{str(r.get('consecutive_years','N/A')):>6} {yield_str:>7} "
            f"{ptype:<8} {payout_str:>7}  {r.get('sector','')}"
        )


if __name__ == "__main__":
    main()
