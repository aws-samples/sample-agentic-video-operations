"""The hls-doctor CLI. Exit code reflects the worst finding severity."""

import sys
from pathlib import Path

from hls_doctor.domain.report.render_text_report import render_text_report
from hls_doctor.domain.report.report_model import InspectionReport
from hls_doctor.entrypoints.parse_cli_arguments import InspectOptions, parse_inspect_options
from hls_doctor.settings.runtime_settings import load_hls_doctor_settings
from hls_doctor.workflows.build_probe_context import build_probe_context
from hls_doctor.workflows.inspect_stream import inspect_stream
from media_ops_contracts.tool_failure import ToolFailure

EXIT_HEALTHY = 0
EXIT_WARNINGS = 1
EXIT_ERRORS = 2
EXIT_FATAL = 3
EXIT_UNUSABLE = 4


def main() -> None:
    raise SystemExit(run(sys.argv[1:]))


def run(argv: list[str]) -> int:
    options = parse_inspect_options(argv)
    try:
        report = run_inspection(options)
    except ToolFailure as failure:
        print(f"{failure.kind.value}: {failure.message}", file=sys.stderr)
        print(failure.next_action, file=sys.stderr)
        return EXIT_UNUSABLE
    emit(report, options)
    return exit_code(report)


def run_inspection(options: InspectOptions) -> InspectionReport:
    settings = load_hls_doctor_settings()
    if options.timeout_seconds is not None:
        settings = settings.model_copy(update={"hls_timeout_seconds": options.timeout_seconds})
    if options.user_agent is not None:
        settings = settings.model_copy(update={"hls_user_agent": options.user_agent})
    context = build_probe_context(
        settings,
        extra_headers=options.headers or None,
        header_origin_url=options.url,
    )
    return inspect_stream(options.url, context, watch_seconds=options.watch_seconds or None)


def emit(report: InspectionReport, options: InspectOptions) -> None:
    rendered_json = report.model_dump_json(indent=2)
    if options.output == "json":
        print(rendered_json)
    else:
        print(render_text_report(report), end="")
    if options.report_path:
        Path(options.report_path).write_text(rendered_json + "\n")


def exit_code(report: InspectionReport) -> int:
    if report.summary.fatal:
        return EXIT_FATAL
    if report.summary.errors:
        return EXIT_ERRORS
    if report.summary.warnings:
        return EXIT_WARNINGS
    return EXIT_HEALTHY
