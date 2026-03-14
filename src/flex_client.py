"""IBKR Flex Web Service client — two-step HTTP request + XML parse."""
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Tuple

import requests

SEND_URL = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest"
GET_URL = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.GetStatement"


@dataclass
class PositionRecord:
    symbol: str
    asset_category: str       # "STK" | "OPT"
    put_call: str             # "P" | "C" | ""
    strike: float
    expiry: str               # "YYYYMMDD" or ""
    multiplier: float
    position: float           # negative = short
    cost_basis_price: float
    mark_price: float
    unrealized_pnl: float
    delta: float
    gamma: float
    theta: float
    vega: float
    underlying_symbol: str = ""   # underlying ticker for OPT positions
    currency: str = "USD"         # position currency (HKD for HK stocks)
    underlying_price: float = 0.0 # underlying mark price from Flex undPrice (0 = not available)


@dataclass
class AccountSummary:
    net_liquidation: float
    gross_position_value: float
    init_margin_req: float
    maint_margin_req: float
    excess_liquidity: float
    available_funds: float
    cushion: float            # 0–1 fraction


class FlexClient:
    def __init__(self, token: str, query_id: str):
        self._token = token
        self._query_id = query_id

    def fetch(self) -> Tuple[List[PositionRecord], AccountSummary]:
        ref_code = self._send_request()
        xml_text = self._get_statement(ref_code)
        return self._parse(xml_text)

    def fetch_from_file(self, path: str) -> Tuple[List[PositionRecord], AccountSummary]:
        """Load positions and account summary from a local Flex XML file."""
        with open(path, "r", encoding="utf-8") as f:
            xml_text = f.read()
        return self._parse(xml_text)

    def _send_request(self) -> str:
        resp = requests.get(SEND_URL, params={"t": self._token, "q": self._query_id, "v": "3"})
        root = ET.fromstring(resp.text)
        status = root.findtext("Status") or ""
        if status != "Success":
            msg = root.findtext("ErrorMessage") or "Unknown error"
            raise RuntimeError(f"Flex SendRequest failed: {msg}")
        return root.findtext("ReferenceCode") or ""

    def _get_statement(self, ref_code: str) -> str:
        import time
        import xml.etree.ElementTree as _ET
        for attempt in range(10):
            resp = requests.get(GET_URL, params={"t": self._token, "q": ref_code, "v": "3"})
            try:
                root = _ET.fromstring(resp.text)
                status = root.findtext("Status") or ""
                if status == "Warn":
                    time.sleep(5)
                    continue
            except Exception:
                pass
            return resp.text
        return resp.text

    def _parse(self, xml_text: str) -> Tuple[List[PositionRecord], AccountSummary]:
        import logging as _log
        root = ET.fromstring(xml_text)
        positions = []
        _undprice_check_done = False
        for pos in root.iter("OpenPosition"):
            a = pos.attrib
            # Skip LOT-level rows; SUMMARY rows already carry the total position.
            if a.get("levelOfDetail", "SUMMARY") == "LOT":
                continue
            # One-time diagnostic: log whether undPrice is present in the Flex data.
            if not _undprice_check_done and a.get("assetCategory", "") == "OPT":
                has_undprice = "undPrice" in a or "underlyingPrice" in a
                _log.getLogger(__name__).info(
                    "Flex undPrice field %s in OPT positions (symbol=%s). "
                    "%s",
                    "FOUND" if has_undprice else "MISSING",
                    a.get("symbol", "?"),
                    "underlying_price will use real data." if has_undprice
                    else "Falling back to option strike as proxy. "
                         "Enable 'Price' field in Flex Query → Open Positions to fix.",
                )
                _undprice_check_done = True
            positions.append(PositionRecord(
                symbol=a.get("symbol", ""),
                asset_category=a.get("assetCategory", ""),
                put_call=a.get("putCall", ""),
                strike=float(a.get("strike") or 0),
                expiry=a.get("expiry", ""),
                multiplier=float(a.get("multiplier") or 1),
                position=float(a.get("position") or 0),
                cost_basis_price=float(a.get("costBasisPrice") or 0),
                mark_price=float(a.get("markPrice") or 0),
                unrealized_pnl=float(a.get("unrealizedPnL") or 0),
                delta=float(a.get("delta") or 0),
                gamma=float(a.get("gamma") or 0),
                theta=float(a.get("theta") or 0),
                vega=float(a.get("vega") or 0),
                underlying_symbol=a.get("underlyingSymbol", ""),
                currency=a.get("currency", "USD"),
                underlying_price=float(
                    a.get("undPrice") or a.get("underlyingPrice") or
                    (a.get("markPrice") if a.get("assetCategory", "") == "STK" else 0) or 0
                ),
            ))
        acct_el = root.find(".//AccountInformation")
        if acct_el is None:
            raise RuntimeError("AccountInformation not found in Flex XML")
        a = acct_el.attrib
        net_liq = float(a.get("netLiquidation") or 0)
        excess_liq = float(a.get("excessLiquidity") or 0)
        cushion = float(a.get("cushion") or 0)
        if cushion == 0 and net_liq > 0:
            cushion = excess_liq / net_liq

        # Fallback: estimate NLV from ChangeInPositionValues (BASE_SUMMARY rows)
        # when AccountInformation doesn't include financial fields.
        if net_liq == 0:
            import logging as _logging
            estimated_nlv = sum(
                float(el.get("endOfPeriodValue") or 0)
                for el in root.iter("ChangeInPositionValue")
                if el.get("currency") == "BASE_SUMMARY"
            )
            if estimated_nlv > 0:
                net_liq = estimated_nlv
                _logging.getLogger(__name__).warning(
                    "AccountInformation missing financial fields; "
                    "NLV estimated from ChangeInPositionValues (excludes cash). "
                    "Add 'Net Asset Value' section to your Flex Query for accurate data."
                )
            else:
                _logging.getLogger(__name__).warning(
                    "AccountInformation missing financial fields (netLiquidation=0). "
                    "Add 'Net Asset Value' section to your Flex Query."
                )

        account = AccountSummary(
            net_liquidation=net_liq,
            gross_position_value=float(a.get("grossPositionValue") or 0),
            init_margin_req=float(a.get("initMarginReq") or 0),
            maint_margin_req=float(a.get("maintMarginReq") or 0),
            excess_liquidity=excess_liq,
            available_funds=float(a.get("availableFunds") or 0),
            cushion=cushion,
        )
        return positions, account
