"""Real-browser smoke and baseline accessibility assertions for release CI."""

from __future__ import annotations

import os
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import sync_playwright

from eii.appliance import write_onboarding_page


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        write_onboarding_page(root / "index.html", "http://127.0.0.1:8080")

        class QuietHandler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(root), **kwargs)

            def log_message(self, format, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                executable = os.environ.get("EII_CHROMIUM_EXECUTABLE")
                browser = playwright.chromium.launch(executable_path=executable)
                page = browser.new_page()
                errors: list[str] = []
                page.on(
                    "console",
                    lambda message: (
                        errors.append(message.text) if message.type == "error" else None
                    ),
                )
                page.goto(f"http://127.0.0.1:{server.server_port}/", wait_until="networkidle")
                assert page.title() == "Connect to School-in-a-Box"
                assert page.locator("html").get_attribute("lang") == "en"
                assert page.locator("main").count() == 1
                assert (
                    page.get_by_role("heading", name="Connect to the classroom server").count() == 1
                )
                assert page.get_by_role("link", name="http://127.0.0.1:8080").evaluate(
                    "element => element.tabIndex >= 0"
                )
                accessibility = Axe().run(page)
                assert accessibility.violations_count == 0, accessibility.response["violations"]
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    main()
