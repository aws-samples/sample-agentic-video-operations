"""Refuse model SQL that does more than one SELECT on the configured table.

This is the runtime's own check, before a call reaches the cluster. It is a second line:
the Hydrolix user in the secret must still be query-only and able to read only that table.
The parser defines the boundary, so sqlglot is pinned exactly in requirements.txt, and
test_hydrolix_bound_model_sql's allowed and refused queries are its regression set.
"""

from collections.abc import Mapping

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from src.settings.runtime_settings import METADATA_DATABASES

# An allowlist, not a denylist: ClickHouse keeps adding functions that read the server
# (currentUser, getSetting, getMacro, hostName, version, …) or other data (dictGet, joinGet).
# Names are as sqlglot 26.33 normalizes them: a function it models by its own name
# (uniq is approx_distinct, formatDateTime is time_to_str), anything else as written.
ALLOWED_FUNCTIONS = frozenset(
    {
        # aggregates
        "count", "count_if", "sum", "sumif", "avg", "avgif", "min", "minif", "max", "maxif",
        "approx_distinct", "uniqexact", "uniqif", "uniqexactif", "quantile", "quantiles",
        "quantileexact", "quantilesexact", "quantiletdigest", "quantilestdigest",
        "quantileif", "stddevpop", "stddevsamp", "varpop", "varsamp", "any_value",
        "anylast", "arg_max", "arg_min", "grouparray", "groupuniqarray", "topk", "corr",
        "row_number", "rank", "dense_rank",
        # date and time
        "now", "today", "yesterday", "todate", "todatetime", "tostartofminute",
        "tostartoffiveminutes", "tostartoftenminutes", "tostartoffifteenminutes",
        "tostartofhour", "tostartofday", "tostartofweek", "tostartofmonth",
        "tostartofinterval", "tohour", "tominute", "tosecond", "todayofweek", "toyyyymmdd",
        "datediff", "date_add", "date_sub", "date_trunc", "time_to_str", "tounixtimestamp",
        "fromunixtimestamp", "totimezone", "parsedatetimebesteffort", "extract",
        "addminutes", "addhours", "adddays", "subtractminutes", "subtracthours",
        "subtractdays", "tointervalminute", "tointervalhour", "tointervalday",
        # math
        "round", "floor", "ceil", "abs", "sqrt", "power", "ln", "log10", "exp", "greatest",
        "least", "intdiv", "modulo", "divide", "multiply", "plus", "minus",
        # strings and URLs
        "lower", "upper", "length", "concat", "substring", "str_position", "replaceall",
        "trim", "splitbychar", "extracturlparameter", "domain", "path", "regexp_like",
        "starts_with", "ends_with", "lowerutf8", "tostring", "pad", "empty", "notempty",
        # conditionals and NULLs
        "if", "case", "multiif", "coalesce", "nullif", "isnull", "isnotnull", "assumenotnull",
        # conversions
        "cast", "toint32", "toint64", "touint32", "touint64", "tofloat32", "tofloat64",
        "todecimal64", "typeof", "toint32orzero", "toint64orzero", "tofloat64ornull",
        # arrays, tuples and JSON
        "explode", "has", "arraymap", "arrayfilter", "arraysort", "struct", "indexof",
        "arrayelement", "json_extract_scalar", "jsonextractint", "jsonextractfloat",
        "jsonhas",
    }
)  # fmt: skip

# These carry the written function name in `this`: sumIf, uniqExact, quantileExact(0.99).
WRITTEN_NAME = (exp.Anonymous, exp.AnonymousAggFunc, exp.ParameterizedAgg)
SOURCES = (exp.Table, exp.Subquery)  # checked further by _check_sources and per SELECT
WRITES = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command)


class QueryRefused(ValueError):
    """The call would read more than the configured table, so it never runs."""


def check_select_query(sql: str, table: str) -> None:
    """Raise QueryRefused unless `sql` is exactly one SELECT that reads only `table`."""
    database, name = table.split(".", 1)
    if database.lower() in METADATA_DATABASES:
        raise QueryRefused(f"{database} is a metadata database, never a data table")
    try:
        statements = [s for s in sqlglot.parse(sql, read="clickhouse") if s is not None]
    except SqlglotError as error:
        raise QueryRefused("the SQL does not parse as one ClickHouse SELECT") from error
    if len(statements) != 1:
        raise QueryRefused("send exactly one statement")
    [statement] = statements
    if not isinstance(statement, exp.Select | exp.SetOperation) or statement.find(*WRITES):
        raise QueryRefused("only SELECT is allowed")
    for query in statement.find_all(exp.Select):
        _check_select_reads_a_source(query, table)
    _check_sources(statement, database, name, table)
    if any(membership.args.get("field") for membership in statement.find_all(exp.In)):
        raise QueryRefused("IN <table> reads another table")
    for function in statement.find_all(exp.Func):
        function_name = _function_name(function)
        if function_name not in ALLOWED_FUNCTIONS:
            shown = function_name or type(function).__name__
            raise QueryRefused(f"the function {shown} is not on the allowed list")
    for query_or_union in statement.find_all(exp.Select, exp.SetOperation):
        if query_or_union.args.get("settings"):
            raise QueryRefused("a SETTINGS clause is refused")


def _check_select_reads_a_source(query: exp.Select, table: str) -> None:
    """A SELECT reads FROM a table or a subquery, never VALUES, UNNEST or nothing at all."""
    source = query.args.get("from")
    if not source or not isinstance(source.this, SOURCES):
        raise QueryRefused(f"every SELECT must read {table}, a subquery or a CTE")
    for join in query.args.get("joins") or []:
        # ARRAY JOIN unfolds an array of the row it is on; it reads no other source.
        if join.args.get("kind") != "ARRAY" and not isinstance(join.this, SOURCES):
            raise QueryRefused(f"a JOIN must read {table}")


def _check_sources(statement: exp.Expression, database: str, name: str, table: str) -> None:
    """Every source is `table`, or a CTE that (through other CTEs) reads it.

    With every SELECT required to have a FROM, this means the query reads `table`: a
    tableless SELECT, a CTE of constants, or CTEs that only read each other are refused.
    """
    cte_bodies = {cte.alias_or_name: cte.this for cte in statement.find_all(exp.CTE)}
    for source in statement.find_all(exp.Table):
        if not isinstance(source.this, exp.Identifier):
            raise QueryRefused("table functions (url, s3, remote, file, cluster, …) are refused")
        is_table = not source.catalog and (source.db, source.name) == (database, name)
        if not is_table and (source.catalog or source.db or source.name not in cte_bodies):
            raise QueryRefused(f"only {table} may be read")
    # A CTE reads the table if its body names it, or names a CTE that does.
    resolved: set[str] = set()
    while True:
        newly = {
            cte
            for cte, body in cte_bodies.items()
            if cte not in resolved
            and any(
                (t.db, t.name) == (database, name) or (not t.db and t.name in resolved)
                for t in body.find_all(exp.Table)
            )
        }
        if not newly:
            break
        resolved |= newly
    for source in statement.find_all(exp.Table):
        if not source.db and source.name not in resolved:
            raise QueryRefused(f"the CTE {source.name} does not read {table}")


def _function_name(function: exp.Func) -> str:
    if isinstance(function, WRITTEN_NAME):
        return str(function.name).lower()
    return function.sql_name().lower()


def check_table_info_request(tool_input: Mapping[str, object], table: str) -> None:
    """get_table_info may describe only the configured table."""
    if (tool_input.get("database"), tool_input.get("table")) != tuple(table.split(".", 1)):
        raise QueryRefused(f"only {table} may be described")
