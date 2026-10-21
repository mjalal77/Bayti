"""Drive the Power Automate portal with Playwright, using a session you sign in to yourself.

    pip install playwright && playwright install chromium

    python tools/powerautomate/pa.py login               # headed browser; sign in (MFA included), then press Enter
    python tools/powerautomate/pa.py list                # list flows in the default environment
    python tools/powerautomate/pa.py runs "<flow name>"  # show run history of a flow
    python tools/powerautomate/pa.py run "<flow name>"   # trigger a manual flow

`login` must run on a machine with a display. It saves the session to
.pa-state/state.json (git-ignored). Treat that file like a password.
Set PA_ENV to an environment id to skip the default environment, PA_HEADED=1 to watch.
"""
import os
import sys
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright

STATE = Path(__file__).resolve().parents[2] / ".pa-state" / "state.json"
BASE = "https://make.powerautomate.com"


def _flows_url() -> str:
    env = os.environ.get("PA_ENV")
    return f"{BASE}/environments/{env}/flows" if env else f"{BASE}/flows"


def login(p) -> None:
    STATE.parent.mkdir(exist_ok=True)
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(BASE)
    input("Sign in in the browser window until you see your flows, then press Enter here... ")
    ctx.storage_state(path=str(STATE))
    STATE.chmod(0o600)
    browser.close()
    print(f"Saved session to {STATE}")


def _open(p):
    if not STATE.exists():
        sys.exit("No saved session. Run: python tools/powerautomate/pa.py login")
    browser = p.chromium.launch(headless=os.environ.get("PA_HEADED") != "1")
    ctx = browser.new_context(storage_state=str(STATE))
    page = ctx.new_page()
    return browser, page


def _goto_flows(page) -> None:
    page.goto(_flows_url())
    if "login.microsoftonline.com" in page.url or "login.live.com" in page.url:
        sys.exit("Session expired. Run the login command again.")
    try:
        page.wait_for_selector("[role=grid], [role=row]", timeout=45_000)
    except PWTimeout:
        sys.exit(f"Flows list did not load (at {page.url}).")


def _open_flow(page, name: str) -> None:
    _goto_flows(page)
    page.get_by_role("link", name=name).first.click()
    page.wait_for_load_state("networkidle")


def list_flows(page) -> None:
    _goto_flows(page)
    for row in page.get_by_role("row").all()[1:]:
        text = " | ".join(t.strip() for t in row.inner_text().split("\n") if t.strip())
        if text:
            print(text)


def runs(page, name: str) -> None:
    _open_flow(page, name)
    page.wait_for_selector("[role=row]", timeout=30_000)
    for row in page.get_by_role("row").all()[1:11]:
        print(" | ".join(t.strip() for t in row.inner_text().split("\n") if t.strip()))


def run(page, name: str) -> None:
    _open_flow(page, name)
    page.get_by_role("button", name="Run").first.click()
    page.get_by_role("button", name="Run flow").click()
    page.get_by_role("button", name="Done").click()
    print(f"Triggered '{name}'. Check history with: runs \"{name}\"")


def main(argv: list[str]) -> None:
    if not argv or argv[0] not in {"login", "list", "runs", "run"}:
        sys.exit(__doc__)
    cmd, args = argv[0], argv[1:]
    with sync_playwright() as p:
        if cmd == "login":
            return login(p)
        browser, page = _open(p)
        try:
            if cmd == "list":
                list_flows(page)
            elif args:
                {"runs": runs, "run": run}[cmd](page, args[0])
            else:
                sys.exit(f"Usage: pa.py {cmd} \"<flow name>\"")
        finally:
            browser.close()


if __name__ == "__main__":
    main(sys.argv[1:])
