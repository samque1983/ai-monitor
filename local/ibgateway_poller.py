#!/usr/bin/env python3
"""
IB Gateway Poller — connects to local IB Gateway, fetches positions +
account summary + real Greeks, POSTs to cloud risk pipeline endpoint.

Usage:
    cd local/
    pip install -r requirements.txt
    cp .env.example .env   # fill in your values
    python ibgateway_poller.py
"""
import math
import os
import sys
import time
import logging
import threading
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

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


def _valid_greek(val) -> bool:
    """Return True if value is a real Greek (not None, not ibapi sentinel)."""
    if val is None:
        return False
    try:
        f = float(val)
        # ibapi uses large sentinels (e.g. UNSET_DOUBLE); real Greeks are tiny
        return abs(f) < 1e10
    except (TypeError, ValueError):
        return False


# ── Black-Scholes math (stdlib only) ──────────────────────────────────────────

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _bs_price(S: float, K: float, T: float, r: float, sigma: float,
              is_call: bool) -> float:
    """Black-Scholes option price."""
    if T <= 0 or sigma <= 0:
        intrinsic = max(0.0, (S - K) if is_call else (K - S))
        return intrinsic
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    if is_call:
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    else:
        return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def _bs_greeks(S: float, K: float, T: float, r: float, sigma: float,
               is_call: bool) -> dict:
    """Compute delta, gamma, theta, vega via Black-Scholes."""
    if T <= 0 or sigma <= 0 or S <= 0:
        delta = 1.0 if (is_call and S > K) else (-1.0 if (not is_call and S < K) else 0.0)
        return {"delta": delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    pdf_d1 = _norm_pdf(d1)
    gamma = pdf_d1 / (S * sigma * sqrtT)
    vega  = S * pdf_d1 * sqrtT / 100.0  # per 1% vol move
    if is_call:
        delta = _norm_cdf(d1)
        theta = (-(S * pdf_d1 * sigma) / (2 * sqrtT)
                 - r * K * math.exp(-r * T) * _norm_cdf(d2)) / 365.0
    else:
        delta = _norm_cdf(d1) - 1.0
        theta = (-(S * pdf_d1 * sigma) / (2 * sqrtT)
                 + r * K * math.exp(-r * T) * _norm_cdf(-d2)) / 365.0
    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega}


def _implied_vol(market_price: float, S: float, K: float, T: float,
                 r: float, is_call: bool) -> Optional[float]:
    """Bisection IV solver. Returns None if it can't converge."""
    if T <= 0 or S <= 0 or K <= 0:
        return None
    intrinsic = max(0.0, (S - K) if is_call else (K - S))
    if market_price <= intrinsic + 1e-8:
        return None
    lo, hi = 1e-4, 5.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        price = _bs_price(S, K, T, r, mid, is_call)
        if abs(price - market_price) < 1e-5:
            return mid
        if price < market_price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


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
    mark_price: float
    unrealized_pnl: float
    delta: float
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
    """Collects positions, account summary, and option Greeks from IB Gateway."""

    def __init__(self, ib_account_id: str):
        EWrapper.__init__(self)
        EClient.__init__(self, wrapper=self)
        self._ib_account_id = ib_account_id
        self.positions: List[PositionData] = []
        self.account = AccountData()
        self._positions_done = threading.Event()
        self._account_done = threading.Event()
        self._errors: List[str] = []
        # Greeks collection — populated after positionEnd
        self._opt_contracts: List[Tuple[Contract, PositionData]] = []
        self._opt_req_map: Dict[int, PositionData] = {}  # reqId → PositionData
        self._greeks_done = threading.Event()
        self._next_req_id = 2000  # start above any system reqIds
        # updatePortfolio data — populated alongside reqAccountUpdates
        self._portfolio_mark: Dict[int, float] = {}    # conId → mark price
        self._portfolio_pnl:  Dict[int, float] = {}    # conId → unrealizedPNL
        self._underlying_prices: Dict[str, float] = {} # symbol → stock price

    # ── EWrapper callbacks ────────────────────────────────────────────────────

    def error(self, reqId: TickerId, errorCode: int, errorString: str, advancedOrderRejectJson=""):
        # 2104/2106/2158 = market data farm connection warnings (non-fatal)
        # 354 = requested market data not subscribed (non-fatal for Greeks)
        if errorCode in (2104, 2106, 2158, 354):
            return
        msg = f"IB error {errorCode}: {errorString} (reqId={reqId})"
        logger.warning(msg)
        self._errors.append(msg)
        # If a mktData request fails, remove it from pending so we don't hang
        if reqId in self._opt_req_map:
            del self._opt_req_map[reqId]
            if not self._opt_req_map:
                self._greeks_done.set()

    def position(self, account: str, contract: Contract, position: float, avgCost: float):
        """Called once per position."""
        ac = contract.secType  # "STK" or "OPT"
        put_call = contract.right if ac == "OPT" else ""
        expiry = contract.lastTradeDateOrContractMonth or ""
        expiry = expiry.replace("-", "")[:8]
        multiplier = float(contract.multiplier or 1)

        p = PositionData(
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
            underlying_symbol=contract.symbol,
            currency=contract.currency or "USD",
        )
        self.positions.append(p)

        # Store contract for later Greeks request
        if ac == "OPT":
            self._opt_contracts.append((contract, p))

    def positionEnd(self):
        """Called when all positions have been delivered."""
        logger.info(f"Received {len(self.positions)} positions "
                    f"({len(self._opt_contracts)} options)")
        self._positions_done.set()

    def updateAccountValue(self, key: str, val: str, currency: str, accountName: str):
        """Called for each account summary field."""
        if currency not in ("USD", "BASE", "") or key not in _ACCT_FIELD_MAP:
            return
        try:
            setattr(self.account, _ACCT_FIELD_MAP[key], float(val))
        except (ValueError, AttributeError):
            pass

    def accountDownloadEnd(self, accountName: str):
        """Called when account download is complete."""
        logger.info(f"Account summary received: NLV=${self.account.net_liquidation:,.0f} "
                    f"cushion={self.account.cushion*100:.1f}%")
        self._account_done.set()

    def updatePortfolio(
        self, contract: Contract, position: float,
        marketPrice: float, marketValue: float,
        averageCost: float, unrealizedPNL: float,
        realizedPNL: float, accountName: str,
    ):
        """Called for each position with IB's internal mark price + P&L."""
        # ibapi sentinel for unavailable price
        if marketPrice is None or abs(marketPrice) > 1e9:
            return
        con_id = contract.conId
        if contract.secType == "STK":
            self._underlying_prices[contract.symbol] = float(marketPrice)
        elif contract.secType == "OPT":
            self._portfolio_mark[con_id] = float(marketPrice)
            self._portfolio_pnl[con_id]  = float(unrealizedPNL) if unrealizedPNL else 0.0

    def tickOptionComputation(
        self, reqId: TickerId, tickType: int, tickAttrib: int,
        impliedVol: float, delta: float, optPrice: float,
        pvDividend: float, gamma: float, vega: float,
        theta: float, undPrice: float,
    ):
        """Called with option model Greeks. tickType 13 = live, 86 = delayed."""
        # Accept both live MODEL_OPTION (13) and delayed MODEL_OPTION (86)
        if tickType not in (13, 86):
            return
        if reqId not in self._opt_req_map:
            return

        p = self._opt_req_map[reqId]
        if _valid_greek(delta):
            p.delta = float(delta)
            p.gamma = float(gamma) if _valid_greek(gamma) else 0.0
            p.theta = float(theta) if _valid_greek(theta) else 0.0
            p.vega  = float(vega)  if _valid_greek(vega)  else 0.0
            logger.debug(f"Greeks: {p.symbol} δ={p.delta:.3f} γ={p.gamma:.4f} "
                         f"θ={p.theta:.4f} ν={p.vega:.4f}")
            del self._opt_req_map[reqId]
            self.cancelMktData(reqId)
            if not self._opt_req_map:
                logger.info("All option Greeks received")
                self._greeks_done.set()

    # ── Greeks request ────────────────────────────────────────────────────────

    def request_greeks(self) -> None:
        """Subscribe to market data for each option position to get real Greeks."""
        if not self._opt_contracts:
            self._greeks_done.set()
            return
        # Fall back to delayed/frozen data when live subscription unavailable.
        # Type 4 = delayed-frozen: live if subscribed, delayed during hours,
        # frozen (last close price) after market close.
        self.reqMarketDataType(4)

        for contract, pos_data in self._opt_contracts:
            # Ensure exchange is set — ibapi position() often leaves it empty
            # while primaryExchange carries the real value (e.g. SEHK for HK options)
            if not contract.exchange:
                if contract.primaryExchange:
                    contract.exchange = contract.primaryExchange
                elif contract.currency == "HKD":
                    contract.exchange = "SEHK"
                else:
                    contract.exchange = "SMART"
            req_id = self._next_req_id
            self._next_req_id += 1
            self._opt_req_map[req_id] = pos_data
            self.reqMktData(req_id, contract, "", False, False, [])
        logger.info(f"Requesting Greeks for {len(self._opt_contracts)} options…")

    def _apply_bs_greeks(self) -> None:
        """Fill delta/gamma/theta/vega + mark_price from updatePortfolio data
        using Black-Scholes.  Called after positions + account are done.
        reqMktData results (if available) will overwrite these values later.
        """
        r = 0.05  # risk-free rate assumption
        filled = 0
        for contract, pos_data in self._opt_contracts:
            con_id = contract.conId

            # Populate mark_price + unrealized_pnl
            if con_id in self._portfolio_mark:
                pos_data.mark_price = self._portfolio_mark[con_id]
            if con_id in self._portfolio_pnl:
                pos_data.unrealized_pnl = self._portfolio_pnl[con_id]

            # Skip if already has real Greeks
            if pos_data.delta != 0.0:
                continue

            mark = pos_data.mark_price
            if not mark or mark <= 0:
                continue

            S = self._underlying_prices.get(pos_data.underlying_symbol)
            if not S or S <= 0:
                continue

            K = pos_data.strike
            if not K or K <= 0:
                continue

            dte = self._dte_days(pos_data.expiry)
            if dte is None:
                continue
            T = max(dte, 0.5) / 365.0  # at least half a day to avoid singularity

            is_call = pos_data.put_call == "C"
            iv = _implied_vol(mark, S, K, T, r, is_call)
            if iv is None:
                # Fall back to a rough delta estimate without IV
                intrinsic = max(0.0, (S - K) if is_call else (K - S))
                pos_data.delta = (0.5 if mark > intrinsic * 1.5
                                  else (0.8 if is_call else -0.8))
                continue

            g = _bs_greeks(S, K, T, r, iv, is_call)
            pos_data.delta = g["delta"]
            pos_data.gamma = g["gamma"]
            pos_data.theta = g["theta"]
            pos_data.vega  = g["vega"]
            filled += 1

        logger.info(f"BS Greeks filled for {filled} options "
                    f"(underlying prices available: {len(self._underlying_prices)})")

    @staticmethod
    def _dte_days(expiry_str: str) -> Optional[int]:
        if not expiry_str or len(expiry_str) != 8:
            return None
        try:
            from datetime import date as _date
            exp = _date(int(expiry_str[:4]), int(expiry_str[4:6]), int(expiry_str[6:]))
            return max(0, (exp - _date.today()).days)
        except ValueError:
            return None


def fetch_from_gateway(
    host: str, port: int, client_id: int, ib_account_id: str,
    timeout: int = 30, greeks_timeout: int = 20,
) -> tuple:
    """Connect to IB Gateway, fetch positions + account summary + Greeks.

    Returns (poller.positions, poller.account).
    Greeks timeout is non-fatal — positions without Greeks are sent with delta=0.
    Raises RuntimeError on connection failure or positions/account timeout.
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

    # Step 1: fetch positions + account summary
    poller.reqAccountUpdates(True, ib_account_id)
    poller.reqPositions()

    account_ok   = poller._account_done.wait(timeout=timeout)
    positions_ok = poller._positions_done.wait(timeout=timeout)

    if not account_ok:
        poller.disconnect()
        raise RuntimeError("Timeout waiting for account summary from IB Gateway")
    if not positions_ok:
        poller.disconnect()
        raise RuntimeError("Timeout waiting for positions from IB Gateway")

    # Step 2: compute BS Greeks from updatePortfolio data (fills all options,
    #         including HK/SEHK which don't respond to reqMktData after close)
    poller._apply_bs_greeks()

    # Step 3: fetch real Greeks via reqMktData (overwrites BS values for US options)
    poller.request_greeks()
    greeks_ok = poller._greeks_done.wait(timeout=greeks_timeout)

    if not greeks_ok:
        missing = len(poller._opt_req_map)
        total   = len(poller._opt_contracts)
        logger.warning(f"Greeks timeout — {missing}/{total} options missing Greeks, "
                       "proceeding with partial data")
        for req_id in list(poller._opt_req_map.keys()):
            poller.cancelMktData(req_id)

    opt_with_greeks = sum(1 for p in poller.positions
                          if p.asset_category == "OPT" and p.delta != 0.0)
    logger.info(f"Greeks summary: {opt_with_greeks}/{len(poller._opt_contracts)} "
                f"options have real Greeks")

    poller.reqAccountUpdates(False, ib_account_id)
    poller.disconnect()

    return poller.positions, poller.account


def upload_to_cloud(
    positions: List[PositionData],
    account: AccountData,
    account_key: str,
    ib_account_id: str,
    cloud_url: str,
    cloud_api_key: str,
    verify_ssl: bool = True,
) -> dict:
    """POST positions + account summary to cloud endpoint."""
    payload = {
        "account_key": account_key,
        "ib_account_id": ib_account_id,
        "positions": [asdict(p) for p in positions],
        "account_summary": asdict(account),
    }
    logger.info(f"Uploading {len(positions)} positions to {cloud_url}…")
    if not verify_ssl:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logger.warning("SSL verification disabled (VERIFY_SSL=false)")
    resp = requests.post(
        cloud_url,
        json=payload,
        headers={"X-API-Key": cloud_api_key, "Content-Type": "application/json"},
        timeout=120,
        verify=verify_ssl,
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

    verify_ssl = os.environ.get("VERIFY_SSL", "true").lower() != "false"
    result = upload_to_cloud(positions, account, account_key, ib_account,
                             cloud_url, cloud_key, verify_ssl=verify_ssl)
    print(f"\nReport generated: {result.get('report_date')} — "
          f"{result.get('alerts', {}).get('red', 0)} red / "
          f"{result.get('alerts', {}).get('yellow', 0)} yellow alerts")
    print(f"View at: {cloud_url.replace('/api/positions', '')}/risk-report")


if __name__ == "__main__":
    main()
