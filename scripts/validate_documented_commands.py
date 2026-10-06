"""Validate documented commands against the repository's declared CLIs."""

import ast
import re
import shlex
import tomllib
from dataclasses import dataclass
from pathlib import Path

JUST_COMMAND = re.compile(r"\bjust ([a-z][a-z-]*)(?: ([^\n;&|]+))?")
UV_RUN = re.compile(r"\buv run(?P<arguments>[^\n`]*)")
PYTHON_SCRIPT = re.compile(r"\b(scripts/[\w./-]+\.py)([^\n`]*)")
TEMPLATE_MARKERS = ("<", ">", "*", "{{", "}}", "$")
UV_OPTIONS_WITH_VALUES = {
    "--default-index",
    "--directory",
    "--env-file",
    "--index",
    "--project",
    "--python",
    "--with",
    "--with-editable",
}


@dataclass(frozen=True)
class ScriptInterface:
    """The positional choices and flags statically declared with argparse."""

    positionals: tuple[frozenset[str] | None, ...]
    flags: tuple[tuple[str, bool], ...]

    @property
    def flag_values(self) -> dict[str, bool]:
        return dict(self.flags)


def read_recipes(justfile: str) -> dict[str, str]:
    """Return each just recipe and its body."""
    recipes: dict[str, str] = {}
    current = None
    for line in justfile.splitlines():
        header = re.match(r"^([a-z_][a-z0-9_-]*)(?: [^:]*)?:(?!=)", line)
        if header and not line.startswith(" "):
            current = header.group(1)
            recipes[current] = ""
        elif current and line.startswith(" "):
            recipes[current] += line + "\n"
    return recipes


def handled_arguments(body: str) -> set[str]:
    """Return literal case arms that route to a real command."""
    handled = set()
    for keys, action in re.findall(r"^\s*([a-z0-9|-]+)\)\s*(.*?);;", body, re.MULTILINE):
        if "_pending" not in action and "_unknown" not in action and "exit 1" not in action:
            handled.update(keys.split("|"))
    return handled


def read_project_scripts(root: Path) -> dict[str, frozenset[str]]:
    """Return distribution name -> project scripts from every workspace package."""
    result: dict[str, frozenset[str]] = {}
    for path in (root / "pyproject.toml", *(root / "samples").glob("*/pyproject.toml")):
        if not path.exists():
            continue
        project = tomllib.loads(path.read_text()).get("project", {})
        if name := project.get("name"):
            result[name] = frozenset(project.get("scripts", {}))
    return result


def read_script_interfaces(root: Path) -> dict[str, ScriptInterface]:
    """Read argparse declarations without importing or running repository scripts."""
    return {
        path.relative_to(root).as_posix(): _read_script_interface(path)
        for path in (root / "scripts").glob("*.py")
    }


def find_command_problems(
    doc: Path,
    spans: list[str],
    recipes: dict[str, str],
    project_scripts: dict[str, frozenset[str]],
    script_interfaces: dict[str, ScriptInterface],
) -> list[str]:
    """Return false just, uv-project-script, and Python-script claims."""
    problems: list[str] = []
    for span in spans:
        normalized = span.replace("\\\n", " ")
        problems.extend(_find_just_problems(doc, normalized, recipes, script_interfaces))
        problems.extend(_find_uv_script_problems(doc, normalized, project_scripts))
        problems.extend(_find_python_script_problems(doc, normalized, script_interfaces))
    return problems


def _find_just_problems(
    doc: Path,
    text: str,
    recipes: dict[str, str],
    script_interfaces: dict[str, ScriptInterface],
) -> list[str]:
    problems = []
    for recipe, raw_arguments in JUST_COMMAND.findall(text):
        if recipe not in recipes:
            problems.append(f"{doc}: `just {recipe}` is not a recipe")
            continue
        body = recipes[recipe]
        if re.fullmatch(r"\s*@?just _pending\S*[^\n]*\n?", body):
            problems.append(f"{doc}: `just {recipe}` is only a placeholder")
            continue
        arguments = _tokens(raw_arguments)
        if (
            not arguments
            or "\\|" in raw_arguments
            or arguments[0].endswith("\\")
            or _is_template(arguments[0])
        ):
            continue
        handled = handled_arguments(body)
        if handled and arguments[0] not in handled:
            problems.append(f"{doc}: `just {recipe} {arguments[0]}` is not implemented")
            continue
        forwarded = _forwarded_python_call(body, arguments, bool(handled))
        if forwarded is not None:
            path, script_arguments = forwarded
            if interface := script_interfaces.get(path):
                problems.extend(_validate_script_arguments(doc, path, script_arguments, interface))
    return problems


def _find_uv_script_problems(
    doc: Path, text: str, project_scripts: dict[str, frozenset[str]]
) -> list[str]:
    problems = []
    for match in UV_RUN.finditer(text):
        package_and_script = _uv_package_and_script(_tokens(match.group("arguments")))
        if package_and_script is None:
            continue
        package, script = package_and_script
        if _is_template(package) or _is_template(script):
            continue
        if package not in project_scripts:
            problems.append(f"{doc}: uv package {package!r} does not exist")
        elif script not in project_scripts[package]:
            problems.append(f"{doc}: {script!r} is not a script of uv package {package!r}")
    return problems


def _forwarded_python_call(
    body: str, arguments: list[str], routes_on_first_argument: bool
) -> tuple[str, list[str]] | None:
    """Return the repository script and arguments a just recipe forwards."""
    selected = body
    forwarded = arguments
    if routes_on_first_argument:
        selected = ""
        for keys, action in re.findall(r"^\s*([a-z0-9|-]+)\)\s*(.*?);;", body, re.MULTILINE):
            if arguments[0] in keys.split("|"):
                selected = action
                forwarded = arguments[1:]
                break
    calls = PYTHON_SCRIPT.findall(selected)
    if len(calls) != 1:
        return None
    path, raw_arguments = calls[0]
    if "{{" not in raw_arguments:
        return None
    fixed = _tokens(re.sub(r"\{\{[^}]+\}\}", "", raw_arguments))
    return path, [*fixed, *forwarded]


def _uv_package_and_script(arguments: list[str]) -> tuple[str, str] | None:
    package = None
    scan_from = 0
    for index, argument in enumerate(arguments):
        if argument == "--package" and index + 1 < len(arguments):
            package = arguments[index + 1]
            scan_from = index + 2
            break
        if argument.startswith("--package="):
            package = argument.split("=", 1)[1]
            scan_from = index + 1
            break
    if package is None:
        return None
    skip_value = False
    for argument in arguments[scan_from:]:
        if argument in {"&&", "||", "|", ";"}:
            break
        if skip_value:
            skip_value = False
            continue
        if argument.startswith("-"):
            option = argument.split("=", 1)[0]
            skip_value = option in UV_OPTIONS_WITH_VALUES and "=" not in argument
            continue
        return package, argument
    return None


def _find_python_script_problems(
    doc: Path, text: str, interfaces: dict[str, ScriptInterface]
) -> list[str]:
    problems = []
    for path, raw_arguments in PYTHON_SCRIPT.findall(text):
        interface = interfaces.get(path)
        if interface is None:
            continue
        problems.extend(_validate_script_arguments(doc, path, _tokens(raw_arguments), interface))
    return problems


def _validate_script_arguments(
    doc: Path, path: str, arguments: list[str], interface: ScriptInterface
) -> list[str]:
    problems: list[str] = []
    flags = interface.flag_values
    positionals: list[str] = []
    skip_value = False
    for token in arguments:
        if token in {"&&", "||", "|", ";"}:
            break
        if skip_value:
            skip_value = False
            continue
        if token.startswith("-"):
            flag = token.split("=", 1)[0]
            if flag not in flags:
                problems.append(f"{doc}: {path} has no {flag} flag")
            elif flags[flag] and "=" not in token:
                skip_value = True
            continue
        positionals.append(token)
    for index, value in enumerate(positionals):
        if _is_template(value):
            continue
        if index >= len(interface.positionals):
            problems.append(f"{doc}: {path} does not accept argument {value!r}")
            continue
        choices = interface.positionals[index]
        if choices is not None and value not in choices:
            problems.append(f"{doc}: {path} has no {value!r} subcommand")
    return problems


def _read_script_interface(path: Path) -> ScriptInterface:
    tree = ast.parse(path.read_text(), filename=str(path))
    enum_values = _read_enum_values(tree)
    positionals: list[frozenset[str] | None] = []
    flags: dict[str, bool] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_argument" or not node.args:
            continue
        names = [arg.value for arg in node.args if isinstance(arg, ast.Constant)]
        if not names:
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
        option_names = [name for name in names if isinstance(name, str) and name.startswith("-")]
        if option_names:
            action = keywords.get("action")
            no_value = isinstance(action, ast.Constant) and action.value in {
                "store_true",
                "store_false",
                "count",
                "help",
                "version",
            }
            for name in option_names:
                flags[name] = not no_value
        else:
            positionals.append(_read_choices(keywords.get("choices"), enum_values))
    return ScriptInterface(tuple(positionals), tuple(sorted(flags.items())))


def _read_enum_values(tree: ast.AST) -> dict[tuple[str, str], str]:
    values: dict[tuple[str, str], str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if (
                isinstance(item, ast.Assign)
                and len(item.targets) == 1
                and isinstance(item.targets[0], ast.Name)
                and isinstance(item.value, ast.Constant)
                and isinstance(item.value.value, str)
            ):
                values[(node.name, item.targets[0].id)] = item.value.value
    return values


def _read_choices(
    node: ast.expr | None, enum_values: dict[tuple[str, str], str]
) -> frozenset[str] | None:
    if node is None:
        return None
    values = []
    for item in node.elts if isinstance(node, ast.List | ast.Tuple | ast.Set) else [node]:
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            values.append(item.value)
        elif (
            isinstance(item, ast.Attribute)
            and isinstance(item.value, ast.Name)
            and (item.value.id, item.attr) in enum_values
        ):
            values.append(enum_values[(item.value.id, item.attr)])
    return frozenset(values) if values else None


def _tokens(text: str) -> list[str]:
    try:
        return shlex.split(text, comments=True)
    except ValueError:
        return text.split()


def _is_template(value: str) -> bool:
    return any(marker in value for marker in TEMPLATE_MARKERS)
