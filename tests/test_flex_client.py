import pytest
from unittest.mock import patch, MagicMock
from src.flex_client import FlexClient, PositionRecord, AccountSummary

SEND_RESPONSE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<FlexStatementOperationInfo>
  <ReferenceCode>777888</ReferenceCode>
  <Status>Success</Status>
</FlexStatementOperationInfo>"""

FLEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement accountId="U123">
      <OpenPositions>
        <OpenPosition symbol="AAPL" assetCategory="STK" putCall="" strike="0"
          expiry="" multiplier="1" position="100" costBasisPrice="150.00"
          markPrice="182.00" unrealizedPnL="3200" delta="1.0"
          gamma="0" theta="0" vega="0"/>
        <OpenPosition symbol="NVDA" assetCategory="OPT" putCall="P" strike="110"
          expiry="20260516" multiplier="100" position="-1" costBasisPrice="3.20"
          markPrice="5.50" unrealizedPnL="-230" delta="-0.35"
          gamma="0.08" theta="-0.12" vega="0.25"/>
      </OpenPositions>
      <AccountInformation netLiquidation="120000" grossPositionValue="95000"
        initMarginReq="18000" maintMarginReq="12300" excessLiquidity="22200"
        availableFunds="25000" cushion="0.185"/>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>"""


def _mock_get(url, *args, **kwargs):
    resp = MagicMock()
    if "SendRequest" in url:
        resp.text = SEND_RESPONSE_XML
    else:
        resp.text = FLEX_XML
    return resp


def test_flex_client_fetch_positions():
    client = FlexClient(token="tok", query_id="qid")
    with patch("src.flex_client.requests.get", side_effect=_mock_get):
        positions, account = client.fetch()
    assert len(positions) == 2
    aapl = next(p for p in positions if p.symbol == "AAPL")
    assert aapl.asset_category == "STK"
    assert aapl.position == 100
    assert aapl.mark_price == 182.00
    nvda = next(p for p in positions if p.symbol == "NVDA")
    assert nvda.put_call == "P"
    assert nvda.strike == 110.0
    assert nvda.delta == -0.35
    assert nvda.gamma == 0.08


def test_flex_client_fetch_account_summary():
    client = FlexClient(token="tok", query_id="qid")
    with patch("src.flex_client.requests.get", side_effect=_mock_get):
        _, account = client.fetch()
    assert account.net_liquidation == 120000.0
    assert account.cushion == pytest.approx(0.185)
    assert account.maint_margin_req == 12300.0


def test_flex_client_cushion_computed_when_missing():
    """When cushion attr absent from XML, derive from excessLiquidity / netLiquidation."""
    xml_no_cushion = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement accountId="U123">
      <OpenPositions/>
      <AccountInformation netLiquidation="120000" grossPositionValue="95000"
        initMarginReq="18000" maintMarginReq="12300" excessLiquidity="22200"
        availableFunds="25000"/>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>"""

    def _mock_no_cushion(url, *args, **kwargs):
        resp = MagicMock()
        resp.text = SEND_RESPONSE_XML if "SendRequest" in url else xml_no_cushion
        return resp

    client = FlexClient(token="tok", query_id="qid")
    with patch("src.flex_client.requests.get", side_effect=_mock_no_cushion):
        _, account = client.fetch()
    # 22200 / 120000 ≈ 0.185
    assert account.cushion == pytest.approx(0.185, rel=1e-3)
    assert account.net_liquidation == 120000.0


def test_flex_client_raises_on_error():
    error_xml = "<FlexStatementOperationInfo><Status>Fail</Status><ErrorMessage>Invalid token</ErrorMessage></FlexStatementOperationInfo>"
    resp = MagicMock()
    resp.text = error_xml
    client = FlexClient(token="bad", query_id="qid")
    with patch("src.flex_client.requests.get", return_value=resp):
        with pytest.raises(RuntimeError, match="Invalid token"):
            client.fetch()


def test_flex_client_parses_currency():
    """PositionRecord.currency is parsed from Flex XML currency attribute."""
    xml_with_currency = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement accountId="U123">
      <OpenPositions>
        <OpenPosition symbol="AAPL" assetCategory="STK" putCall="" strike="0"
          expiry="" multiplier="1" position="100" costBasisPrice="150.00"
          markPrice="182.00" unrealizedPnL="3200" delta="0"
          gamma="0" theta="0" vega="0" currency="USD"/>
        <OpenPosition symbol="CHT" assetCategory="STK" putCall="" strike="0"
          expiry="" multiplier="1" position="2000" costBasisPrice="75.00"
          markPrice="80.00" unrealizedPnL="10000" delta="0"
          gamma="0" theta="0" vega="0" currency="HKD"/>
      </OpenPositions>
      <AccountInformation netLiquidation="120000" grossPositionValue="95000"
        initMarginReq="18000" maintMarginReq="12300" excessLiquidity="22200"
        availableFunds="25000" cushion="0.185"/>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>"""

    def _mock_currency(url, *args, **kwargs):
        resp = MagicMock()
        resp.text = SEND_RESPONSE_XML if "SendRequest" in url else xml_with_currency
        return resp

    client = FlexClient(token="tok", query_id="qid")
    with patch("src.flex_client.requests.get", side_effect=_mock_currency):
        positions, _ = client.fetch()
    aapl = next(p for p in positions if p.symbol == "AAPL")
    cht = next(p for p in positions if p.symbol == "CHT")
    assert aapl.currency == "USD"
    assert cht.currency == "HKD"
