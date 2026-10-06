"""The `hls-doctor inspect` option surface (spec §5), parsed into a typed model."""

import argparse

from pydantic import BaseModel, Field


class InspectOptions(BaseModel):
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    user_agent: str | None = None
    timeout_seconds: float | None = None
    watch_seconds: float = 0
    output: str = "text"
    report_path: str | None = None
    redact_query_params: bool = False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hls-doctor", description="Diagnose an HLS presentation from its manifest URL."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Inspect one HLS manifest URL.")
    inspect.add_argument("url", help="Multivariant or Media Playlist URL (.m3u8)")
    inspect.add_argument(
        "--header", action="append", default=[], metavar="NAME: VALUE",
        help="Extra request header; repeatable",
    )  # fmt: skip
    inspect.add_argument("--user-agent", help="Override the request User-Agent")
    inspect.add_argument(
        "--watch", type=float, default=0, metavar="SECONDS",
        help="Also watch the live playlists for this long and correlate live defects",
    )  # fmt: skip
    inspect.add_argument("--timeout", type=float, metavar="SECONDS", help="Request timeout")
    inspect.add_argument("--output", choices=["text", "json"], default="text")
    inspect.add_argument("--report", metavar="PATH", help="Also write the JSON report here")
    inspect.add_argument(
        "--redact-query-params", action="store_true",
        help="Redact every query value in reports, not just credential-shaped ones",
    )  # fmt: skip
    return parser


def parse_inspect_options(argv: list[str] | None = None) -> InspectOptions:
    arguments = build_parser().parse_args(argv)
    headers: dict[str, str] = {}
    for raw in arguments.header:
        name, _, value = raw.partition(":")
        headers[name.strip()] = value.strip()
    return InspectOptions(
        url=arguments.url,
        headers=headers,
        user_agent=arguments.user_agent,
        watch_seconds=arguments.watch,
        timeout_seconds=arguments.timeout,
        output=arguments.output,
        report_path=arguments.report,
        redact_query_params=arguments.redact_query_params,
    )
