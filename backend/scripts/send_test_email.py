"""Send one real test e-mail through the configured provider (Phase 5 acceptance).

    cd backend
    .venv\\Scripts\\python scripts\\send_test_email.py --to you@example.com [--language ar] [--template task_urgent]

It uses EMAIL_PROVIDER and its key from the environment / backend/.env, exactly as the
server does. Nothing is written to the database; the key and the address are not printed
(the address is shown masked).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.services.email.providers import OutgoingEmail, SendError, get_provider, mask  # noqa: E402
from app.services.email.templates import LANGUAGES, TEMPLATES, render  # noqa: E402

SAMPLE = {"title": "Quarterly report", "who": "Office Assistant", "date": "2026-11-12", "time": "17:00:00",
          "start": "10:00:00", "end": "11:00:00"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--to", required=True, help="the sandbox / test address")
    parser.add_argument("--language", choices=LANGUAGES, default="en")
    parser.add_argument("--template", choices=TEMPLATES, default="test")
    args = parser.parse_args()

    settings = get_settings()
    provider = get_provider(settings)
    if provider.name in ("off", "fake"):
        print(f"EMAIL_PROVIDER is '{provider.name}': nothing would be sent. Set smtp, resend or sendgrid.")
        return 2
    rendered = render(args.template, args.language, SAMPLE, "there", settings.app_link_url)
    try:
        message_id = provider.send(OutgoingEmail(to=args.to, subject=rendered.subject, text=rendered.text,
                                                 html=rendered.html))
    except SendError as error:
        print(f"FAILED ({'permanent' if error.permanent else 'temporary'}): {error.reason}")
        return 1
    note = " (console provider: logged, not really sent)" if provider.name == "console" else ""
    print(f"sent via {provider.name} to {mask(args.to)}: message id {message_id}{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
