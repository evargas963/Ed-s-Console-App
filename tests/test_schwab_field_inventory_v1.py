"""The field inventory reads Schwab's answer as sent: on a real /chains answer every contract
field is one path under its side, the expiry and strike keys are `*`, and every value's JSON
type is named (null included).
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.schwab_field_inventory import chain_paths

ANSWER = json.loads(
    (Path(__file__).parent / "fixtures" / "real_schwab_chain_tsla_2026_10_09.json").read_text(
        encoding="utf-8"
    )
)["answer"]


#: RFC 8259's value types, by the Python type json.loads gives each
JSON_TYPE = {
    type(None): "null",
    bool: "bool",
    int: "number",
    float: "number",
    str: "string",
    dict: "object",
    list: "array",
}


def _json_type(v) -> str:
    return JSON_TYPE[type(v)]


def test_every_contract_field_of_a_real_chain_is_one_path_under_its_side():
    found: dict[str, str] = {}
    chain_paths(ANSWER, found)
    for side in ("callExpDateMap", "putExpDateMap"):
        contracts = [c for strikes in ANSWER[side].values() for cs in strikes.values() for c in cs]
        assert contracts, f"the real answer lists {side} contracts"
        fields = {k for c in contracts for k in c}
        on_side = {p for p in found if p.startswith(f"chains.{side}.*.")}
        assert {p.split(".", 3)[3].split(".")[0] for p in on_side} == fields
        for k in fields:
            sent = {_json_type(c[k]) for c in contracts if k in c}
            assert found[f"chains.{side}.*.{k}"] in sent
    # no expiry date or strike is a field name
    expiry = next(iter(ANSWER["callExpDateMap"]))
    assert not any(expiry in p for p in found)
    for k, v in ANSWER.items():
        if not k.endswith("ExpDateMap"):
            assert f"chains.{k}" in found
            if not isinstance(v, (dict, list)):
                assert found[f"chains.{k}"] == _json_type(v)
