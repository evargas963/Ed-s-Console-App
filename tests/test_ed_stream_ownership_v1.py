"""RC-UI-1 (#10) — the rebuilt shell has exactly ONE streaming-control writer, static/js/ed-stream.js,
which REUSES the canonical command-generation endpoints + the shipped EdOptionsSubscription gate. No
other shell module writes streaming control, and ed-stream.js invents no parallel owner/counter. This
is the prerequisite that lets Flow/Chain add contract selection without two tabs corrupting the active
ticker/contract/subscription (the server's command_generation/superseded rule + this client gate)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "static" / "js"


def test_only_ed_stream_writes_streaming_control():
    # Future-proof: EVERY rebuilt-shell module (static/js/ed-*.js) EXCEPT ed-stream.js must route
    # streaming control through EdStream. Globbed, not a fixed list — so Flow/Chain (and any new
    # shell module) are covered automatically the moment they are added.
    shell_js = sorted(p for p in JS.glob("ed-*.js") if p.name != "ed-stream.js")
    assert shell_js, "expected ed-*.js shell modules"
    for p in shell_js:
        src = p.read_text(encoding="utf-8")
        assert "streaming/active-option-contract" not in src, p.name + " must route contract control through EdStream"
        assert "streaming/active-ticker" not in src, p.name + " must route ticker control through EdStream"


def test_ed_stream_reuses_the_canonical_mechanism_not_a_new_owner():
    s = (JS / "ed-stream.js").read_text(encoding="utf-8")
    # routes through the canonical endpoints
    assert "/api/streaming/active-option-contract" in s
    assert "/api/streaming/active-ticker" in s
    # reuses the shipped EdOptionsSubscription gate/validator (does not reimplement a gate)
    assert "EdOptionsSubscription" in s
    assert "createSubscriptionGate" in s and "validateSubscriptionAck" in s and "mayCommit" in s
    # honors the server's superseded verdict and reads the server-issued command_generation
    assert "superseded" in s
    assert "command_generation" in s


def test_shell_loads_the_shared_subscription_lib_before_ed_stream():
    html = (ROOT / "static" / "console.html").read_text(encoding="utf-8")
    i_sub = html.find("options_subscription.js")
    i_stream = html.find("ed-stream.js")
    assert i_sub != -1 and i_stream != -1 and i_sub < i_stream, \
        "options_subscription.js (EdOptionsSubscription) must load before ed-stream.js consumes it"
