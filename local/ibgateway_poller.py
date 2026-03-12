#!/usr/bin/env python3
"""
IB Gateway Poller — connects to local IB Gateway, fetches positions +
account summary, POSTs to cloud risk pipeline endpoint.

Usage:
    cd local/
    pip install -r requirements.txt
    cp .env.example .env   # fill in your values
    python ibgateway_poller.py
"""
import os
import sys
import time
import logging
import threading
from dataclasses import dataclass, asdict
from typing import List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── ibapi import (must be installed via pip install ibapi) ─────────────────────
try:
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper
    from ibapi.contract import Contract
    from ibapi.common import TickerId
except ImportError:
    print("ERROR: ibapi not installed. Run: pip install ibapi==10.19.2")
    sys.exit(1)


@dataclass
class PositionData:
    symbol: str
    asset_category: str       # "STK" | "OPT"
    put_call: str             # "P" | "C" | ""
    strike: float
    expiry: str               # "YYYYMMDD" or ""
    multiplier: float
    position: float
    cost_basis_price: float
    mark_price: float         # 0.0 — cloud fills via market data
    unrealized_pnl: float     # 0.0
    delta: float              # 0.0 — cloud enriches
    gamma: float
    theta: float
    vega: float
    underlying_symbol: str
    currency: str


@dataclass
class AccountData:
    net_liquidation: float = 0.0
    gross_position_value: float = 0.0
    init_margin_req: float = 0.0
    maint_margin_req: float = 0.0
    excess_liquidity: float = 0.0
    available_funds: float = 0.0
    cushion: float = 0.0


_ACCT_FIELD_MAP = {
    "NetLiquidation": "net_liquidation",
    "GrossPositionValue": "gross_position_value",
    "InitMarginReq": "init_margin_req",
    "MaintMarginReq": "maint_margin_req",
    "ExcessLiquidity": "excess_liquidity",
    "AvailableFunds": "available_funds",
    "Cushion": "cushion",
}


class IBPoller(EWrapper, EClient):
    """Collects positions and account summary from IB Gateway."""

    def __init__(self, ib_account_id: str):
        EWrapper.__init__(self)
        EClient.__init__(self, wrapper=self)
        self._ib_account_id = ib_account_id
        self.positions: List[PositionData] = []
        self.account = AccountData()
        self._positions_done = threading.Event()
        self._account_done = threading.Event()
        self._errors: List[str] = []

    # ── EWrapper callbacks ────────────────────────────────────────────────────

    def error(self, reqId: TickerId, errorCode: int, errorString: str, advancedOrderRejectJson=""):
        # 2104/2106/2158 = market data farm connection warnings (non-fatal)
        if errorCode in (2104, 2106, 2158):
            return
        msg = f"IB error {errorCode}: {errorString} (reqId={reqId})"
        logger.warning(msg)
        self._errors.append(msg)

    def position(self, account: str, contract: Contract, position: float, avgCost: float):
        """Called once per position."""
        ac = contract.secType  # "STK" or "OPT"
        put_call = contract.right if ac == "OPT" else ""  # "P" or "C"
        expiry = contract.lastTradeDateOrContractMonth or ""
        expiry = expiry.replace("-", "")[:8]
        multiplier = float(contract.multiplier or 1)
        underlying = contract.symbol

        self.positions.append(PositionData(
            symbol=contract.localSymbol or contract.symbol,
            asset_category=ac,
            put_call=put_call,
            strike=float(contract.strike or 0),
            expiry=expiry,
            multiplier=multiplier,
            position=position,
            cost_basis_price=avgCost / multiplier if multiplier > 1 else avgCost,
            mark_price=0.0,
            unrealized_pnl=0.0,
            delta=0.0, gamma=0.0, theta=0.0, vega=0.0,
            underlying_symbol=underlying,
            currency=contract.currency or "USD",
        ))

    def positionEnd(self):
        """Called when all positions have been delivered."""
        logger.info(f"Received {len(self.positions)} positions")
        self._positions_done.set()

    def updateAccountValue(self, key: str, val: str, currency: str, accountName: str):
        """Called for each account summary field."""
        if currency not in ("USD", "BASE", "") or key not in _ACCT_FIELD_MAP:
            return
        try:
            field_name = _ACCT_FIELD_MAP[key]
            setattr(self.account, field_name, float(val))
        except (ValueError, AttributeError):
            pass

    def accountDownloadEnd(self, accountName: str):
        """Called when account download is complete."""
        logger.info(f"Account summary received: NLV=${self.account.net_liquidation:,.0f} "
                    f"cushion={self.account.cushion*100:.1f}%")
        self._account_done.set()


def fetch_from_gateway(
    host: str, port: int, client_id: int, ib_account_id: str, timeout: int = 30
) -> tuple:
    """Connect to IB Gateway, fetch positions + account summary.

    Returns (poller.positions, poller.account).
    Raises RuntimeError on connection failure or timeout.
    """
    poller = IBPoller(ib_account_id)
    poller.connect(host, port, clientId=client_id)

    thread = threading.Thread(target=poller.run, daemon=True)
    thread.start()

    time.sleep(1)

    if not poller.isConnected():
        raise RuntimeError(f"Failed to connect to IB Gateway at {host}:{port}. "
                           "Make sure IB Gateway is running and API connections are enabled.")

    logger.info(f"Connected to IB Gateway at {host}:{port}")

    poller.reqAccountUpdates(True, ib_account_id)
    poller.reqPositions()

    account_ok = poller._account_done.wait(timeout=timeout)
    positions_ok = poller._positions_done.wait(timeout=timeout)

    poller.reqAccountUpdates(False, ib_account_id)
    poller.disconnect()

    if not account_ok:
        raise RuntimeError("Timeout waiting for account summary from IB Gateway")
    if not positions_ok:
        raise RuntimeError("Timeout waiting for positions from IB Gateway")

    return poller.positions, poller.account


def upload_to_cloud(
    positions: List[PositionData],
    account: AccountData,
    account_key: str,
    ib_account_id: str,
    cloud_url: str,
    cloud_api_key: str,
) -> dict:
    """POST positions + account summary to cloud endpoint."""
    payload = {
        "account_key": account_key,
        "ib_account_id": ib_account_id,
        "positions": [asdict(p) for p in positions],
        "account_summary": asdict(account),
    }
    logger.info(f"Uploading {len(positions)} positions to {cloud_url}…")
    resp = requests.post(
        cloud_url,
        json=payload,
        headers={"X-API-Key": cloud_api_key, "Content-Type": "application/json"},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    host        = os.environ.get("IB_GATEWAY_HOST", "127.0.0.1")
    port        = int(os.environ.get("IB_GATEWAY_PORT", "4001"))
    client_id   = int(os.environ.get("IB_CLIENT_ID", "10"))
    ib_account  = os.environ.get("IB_ACCOUNT_ID", "")
    cloud_url   = os.environ.get("CLOUD_API_URL", "")
    cloud_key   = os.environ.get("CLOUD_API_KEY", "")
    account_key = os.environ.get("ACCOUNT_KEY", "ALICE")

    if not ib_account:
        print("ERROR: IB_ACCOUNT_ID not set in .env")
        sys.exit(1)
    if not cloud_url or not cloud_key:
        print("ERROR: CLOUD_API_URL and CLOUD_API_KEY must be set in .env")
        sys.exit(1)

    logger.info(f"Fetching positions for account {ib_account}…")
    positions, account = fetch_from_gateway(host, port, client_id, ib_account)
    logger.info(f"Fetched {len(positions)} positions")

    result = upload_to_cloud(positions, account, account_key, ib_account,
                             cloud_url, cloud_key)
    print(f"\nReport generated: {result.get('report_date')} — "
          f"{result.get('alerts', {}).get('red', 0)} red / "
          f"{result.get('alerts', {}).get('yellow', 0)} yellow alerts")
    print(f"View at: {cloud_url.replace('/api/positions', '')}/risk-report")


if __name__ == "__main__":
    main()
