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

    def _send_request(self) -> str:
        resp = requests.get(SEND_URL, params={"t": self._token, "q": self._query_id, "v": "3"})
        root = ET.fromstring(resp.text)
        status = root.findtext("Status") or ""
        if status != "Success":
            msg = root.findtext("ErrorMessage") or "Unknown error"
            raise RuntimeError(f"Flex SendRequest failed: {msg}")
        return root.findtext("ReferenceCode") or ""

    def _get_statement(self, ref_code: str) -> str:
        resp = requests.get(GET_URL, params={"t": self._token, "q": ref_code, "v": "3"})
        return resp.text

    def _parse(self, xml_text: str) -> Tuple[List[PositionRecord], AccountSummary]:
        root = ET.fromstring(xml_text)
        positions = []
        for pos in root.iter("OpenPosition"):
            a = pos.attrib
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
        if net_liq == 0:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "AccountInformation missing financial fields (netLiquidation=0). "
                "Edit your Flex Query: Account Information section → enable "
                "Net Liquidation, Excess Liquidity, Cushion, Available Funds, "
                "Initial Margin Req, Maintenance Margin Req."
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
