"""Contract -> underlying identity: vendor OSI root, not prefix match.

# universal-scope-ok: fixtures use banked CDE/CRWD/TSLA/SPY vendor symbols as
# examples of the enrolled-universe capture path, not a single-ticker product claim.
"""
from __future__ import annotations


def test_real_cde_osi_is_not_ticker_c():
    """Prefix match is not identity: real CDE vendor symbol must not bind to C."""
    from instrument_identity import option_underlying_root, vendor_option_root
    from app.options.order_flow.streaming import _contract_matches_underlying

    cde = "CDE   260904C00005000"
    assert vendor_option_root(cde) == "CDE"
    assert option_underlying_root("C") == "C"
    assert option_underlying_root("CDE") == "CDE"
    assert _contract_matches_underlying(cde, "CDE") is True
    assert _contract_matches_underlying(cde, "C") is False


def test_a_does_not_match_aa_or_aal_osi_roots():
    """Short equity roots must not prefix-match longer distinct underlyings."""
    from instrument_identity import vendor_option_root
    from app.options.order_flow.streaming import _contract_matches_underlying

    aa = "AA    260904C00050000"
    aal = "AAL   260904C00050000"
    a = "A     260904C00050000"
    assert vendor_option_root(aa) == "AA"
    assert vendor_option_root(aal) == "AAL"
    assert vendor_option_root(a) == "A"
    assert _contract_matches_underlying(aa, "A") is False
    assert _contract_matches_underlying(aal, "A") is False
    assert _contract_matches_underlying(a, "A") is True


def test_exact_underlying_matches_real_vendor_symbols():
    from app.options.order_flow.streaming import _contract_matches_underlying

    assert _contract_matches_underlying("CDE   260904C00013000", "CDE") is True
    assert _contract_matches_underlying("CRWD  260918C00038750", "CRWD") is True
    assert _contract_matches_underlying("TSLA  260831C00160000", "TSLA") is True
    assert _contract_matches_underlying("SPY   260820C00767000", "SPY") is True


def test_index_alias_uses_broker_roots_not_invented_weeklies():
    """$SPX/SPX share OSI root SPX via BROKER_INDEX_BARE_ROOTS. SPXW is not aliased."""
    from instrument_identity import option_underlying_root, vendor_option_root
    from app.options.order_flow.streaming import _contract_matches_underlying

    assert option_underlying_root("$SPX") == "SPX"
    assert option_underlying_root("SPX") == "SPX"
    spx_osi = "SPX   260918C05000000"
    assert vendor_option_root(spx_osi) == "SPX"
    assert _contract_matches_underlying(spx_osi, "$SPX") is True
    assert _contract_matches_underlying(spx_osi, "SPX") is True
    weekly = "SPXW  260918C05000000"
    assert vendor_option_root(weekly) == "SPXW"
    assert _contract_matches_underlying(weekly, "$SPX") is False


def test_non_osi_symbol_is_fail_closed():
    from instrument_identity import vendor_option_root
    from app.options.order_flow.streaming import _contract_matches_underlying

    assert vendor_option_root("CDE") == ""
    assert vendor_option_root("") == ""
    assert _contract_matches_underlying("CDE", "CDE") is False
    assert _contract_matches_underlying(None, "CDE") is False


def test_vendor_option_root_reads_symbol_never_constructs():
    import ast
    import inspect
    from app.options.contracts.default import pick_atm_call_symbol
    from instrument_identity import vendor_option_root

    src = inspect.getsource(vendor_option_root)
    assert "raw[:6]" in src
    tree = ast.parse(inspect.getsource(pick_atm_call_symbol))
    joined = [n for n in ast.walk(tree) if isinstance(n, ast.JoinedStr)]
    assert not joined, "pick_atm_call_symbol must not f-string a vendor symbol"
    assert 'raw.get("symbol")' in inspect.getsource(pick_atm_call_symbol)


def test_switch_underlying_replaces_stale_foreign_contract(monkeypatch):
    import app.options.order_flow.streaming as ofs

    written = []
    monkeypatch.setattr(ofs, "write_active_ticker_signal", lambda *_a, **_k: None)
    monkeypatch.setattr(ofs, "write_active_option_contract_signal", lambda s: written.append(s))
    monkeypatch.setattr(ofs, "forget_unsubscribed_symbols", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "app.options.contracts.default.default_option_contract",
        lambda ticker, chain_db_path=None: "C     260904C00050000",
    )
    ofs._active_option_contract = "CDE   260904C00013000"
    ofs._active_ticker = "CDE"
    try:
        assert ofs.set_streaming_active_ticker("C") is True
        assert ofs._active_option_contract == "C     260904C00050000"
        assert written[-1] == "C     260904C00050000"
    finally:
        ofs._active_option_contract = None
        ofs._active_ticker = None


def test_same_underlying_manual_contract_is_kept(monkeypatch):
    import app.options.order_flow.streaming as ofs

    written = []
    monkeypatch.setattr(ofs, "write_active_ticker_signal", lambda *_a, **_k: None)
    monkeypatch.setattr(ofs, "write_active_option_contract_signal", lambda s: written.append(s))
    monkeypatch.setattr(ofs, "forget_unsubscribed_symbols", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "app.options.contracts.default.default_option_contract",
        lambda ticker, chain_db_path=None: "CDE   260904C00020000",
    )
    manual = "CDE   260904C00013000"
    ofs._active_option_contract = manual
    ofs._active_ticker = None
    try:
        assert ofs.set_streaming_active_ticker("CDE") is True
        assert ofs._active_option_contract == manual
        assert written == []
    finally:
        ofs._active_option_contract = None
        ofs._active_ticker = None

def test_spxw_matches_dollar_spx_only_via_banked_chain():
    """Real 2026-09-04 $SPX complete chain uses OSI root SPXW, not SPX.

    Without chain evidence SPXW must not alias to $SPX (no invented weekly map).
    With the vendor chain, the same root matches $SPX and still does not match SPY.
    """
    from app.options.order_flow.streaming import _contract_matches_underlying

    weekly = "SPXW  260904C07735000"
    assert _contract_matches_underlying(weekly, "$SPX") is False
    assert _contract_matches_underlying(weekly, "SPY") is False

    cap = {
        "ticker": "$SPX",
        "expiry": "2026-09-04",
        "contracts": [
            {"symbol": weekly},
        ],
    }

    def _nearest(db_path, ticker, *, on_or_after_expiry):
        tk = (ticker or "").strip().upper()
        if tk in ("$SPX", "SPX"):
            return cap
        return None

    import calibration.complete_chain_capture as ccc
    import app.options.order_flow.streaming as ofs
    orig = ccc.nearest_complete_chain_capture
    ccc.nearest_complete_chain_capture = _nearest
    try:
        db = "unused.db"
        assert ofs._contract_matches_underlying(weekly, "$SPX", chain_db_path=db) is True
        assert ofs._contract_matches_underlying(weekly, "SPY", chain_db_path=db) is False
        assert ofs._contract_matches_underlying("SPY   260904C00772000", "$SPX", chain_db_path=db) is False
    finally:
        ccc.nearest_complete_chain_capture = orig


def test_switch_underlying_clears_when_no_replacement(monkeypatch):
    """CDE -> C with no banked C chain must not keep the CDE contract."""
    import app.options.order_flow.streaming as ofs

    written = []
    monkeypatch.setattr(ofs, "write_active_ticker_signal", lambda *_a, **_k: None)
    monkeypatch.setattr(ofs, "write_active_option_contract_signal", lambda s: written.append(s))
    monkeypatch.setattr(ofs, "forget_unsubscribed_symbols", lambda *_a, **_k: None)
    monkeypatch.setattr(ofs, "clear_symbol", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "app.options.contracts.default.default_option_contract",
        lambda ticker, chain_db_path=None: None,
    )
    ofs._active_option_contract = "CDE   260904C00013000"
    ofs._active_ticker = "CDE"
    try:
        assert ofs.set_streaming_active_ticker("C") is True
        assert ofs._active_option_contract is None
        assert written[-1] == ""
    finally:
        ofs._active_option_contract = None
        ofs._active_ticker = None
