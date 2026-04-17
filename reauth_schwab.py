"""
Schwab OAuth reauth script.
Run: python reauth_schwab.py  (or: python -m reauth_schwab)

1. Deletes the existing token file (if present)
2. Ensures the local callback server is bound before opening the browser
3. Opens your browser to Schwab's OAuth page
4. After you sign in and approve, saves a new token to schwab_token.json
5. Verifies the token file exists — raises RuntimeError if missing

401 on /accounts/accountNumbers: If market data works but accounts returns 401,
your Schwab app is likely registered for "Market Data" only. At developer.schwab.com,
ensure the app uses "Accounts and Trading Production" (includes market data).
Then run: python reauth_schwab.py to get a new token with account scope.
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

APP_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(APP_DIR))

from config import build_config
from schwab_client import auth_is_refreshable, inspect_token_file, run_login_flow, run_manual_flow


def reauth():
    manual = "--manual" in sys.argv or "-m" in sys.argv
    cfg = build_config(str(APP_DIR))
    token_path = os.path.abspath(cfg.token_path)

    print("=" * 60)
    print("SCHWAB REAUTH")
    print("=" * 60)
    print(f"Token path: {token_path}")
    print(f"Callback:   {cfg.callback_url}")
    print()
    if manual:
        print("Using MANUAL flow — you will copy/paste URLs (no local server, no cert warning).")
    else:
        print("IMPORTANT — When Schwab redirects you back:")
        print("  Your browser will show a certificate warning (self-signed).")
        print("  You MUST click 'Advanced' → 'Proceed to 127.0.0.1' (or equivalent)")
        print("  for the token to be saved. If the token isn't created, run:")
        print("    python reauth_schwab.py --manual")
    print()

    if os.path.exists(token_path):
        try:
            os.remove(token_path)
            print("Removed existing token file.")
        except Exception as e:
            print(f"Could not remove old token: {e}")
            print("Continuing — login flow will overwrite it.")

    flow_fn = run_manual_flow if manual else run_login_flow
    print("\n" + ("Follow prompts to copy/paste URLs..." if manual else "Opening browser for Schwab login (waiting for callback server)..."))
    try:
        ok, msg = flow_fn(
            api_key=cfg.api_key,
            app_secret=cfg.app_secret,
            callback_url=cfg.callback_url,
            token_path=token_path,
        )
        if ok:
            print(f"\n✅ SUCCESS: Token written to {token_path}")
            print("You can restart the server now.")
            if os.path.exists(token_path):
                inv = inspect_token_file(token_path)
                print("\n--- Post-reauth token validation (secrets redacted) ---")
                print(f"  token path:        {token_path}")
                print(f"  refreshable:       {auth_is_refreshable(inv)}")
                print(f"  scope:             {inv.scope_value!r}")
                print(f"  expires_at present: {inv.has_expires_at}")
                print(f"  structure message: {inv.message}")
                print("--- End validation ---")
                if not auth_is_refreshable(inv):
                    print(
                        "\n❌ FAILURE: Token file has no usable refresh_token after reauth. "
                        "Remediation: python reauth_schwab.py --manual"
                    )
                    sys.exit(1)
        else:
            print(f"\n❌ FAILURE: {msg}")
            if not manual:
                print("\nIf you saw the callback page but no token was created:")
                print("  - Did you click through the browser's certificate warning?")
                print("  - Try: python reauth_schwab.py --manual  (avoids cert issue)")
            print("  - Check that your Schwab app's callback URL exactly matches:")
            print(f"    {cfg.callback_url}")
            sys.exit(1)
    except RuntimeError as e:
        print(f"\n❌ FAILURE: {e}")
        if not manual:
            print("\nIf you saw the callback page but no token was created:")
            print("  - Did you click through the browser's certificate warning?")
            print("  - Try: python reauth_schwab.py --manual  (avoids cert issue)")
        print("  - Check that your Schwab app's callback URL exactly matches:")
        print(f"    {cfg.callback_url}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ FAILURE: {e}")
        traceback.print_exc()
        if not manual:
            print("\nIf you completed login and got a callback page:")
            print("  The browser must ACCEPT the self-signed cert to reach the local server.")
            print("  Or run: python reauth_schwab.py --manual  (no local server needed)")
        sys.exit(1)


if __name__ == "__main__":
    reauth()
