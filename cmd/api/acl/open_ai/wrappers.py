"""Wrap ChatGPT tools to inject identity and hide other companies' plans."""

import functools
import inspect
import re
from typing import Any, Callable

from langchain_core.tools import Tool, create_schema_from_function

from cmd.api.acl.open_ai.identity import current_id_external_company, current_id_external_user

_COMPANY_CHECKED_PLAN_TOOLS = {
    "get_improvement_plan_by_inventory",
    "get_improvement_plan_problem",
    "get_improvement_plan_method",
    "get_improvement_plan_reasoning",
}


def wrap_chatgpt_tools(tools: list[Tool]) -> list[Tool]:
    """Return ChatGPT tools with identity injected and Tavily-safe schemas."""

    return [_wrap_chatgpt_tool(tool) for tool in tools]


def _strip_identity_from_description(description: str | None) -> str:
    """Remove sentences that mention id_external_user from a tool description."""

    if not description:
        return description or ""
    sentences = re.split(r"(?<=\.)\s+", description.strip())
    kept = [sentence for sentence in sentences if "id_external_user" not in sentence]
    return " ".join(kept)


def _assert_plan_belongs_to_user_company(id_external_inventory: Any) -> None:
    """Reject a plan that does not belong to the bound user's company."""

    from cmd.api.tools.mongo_tools import _company_id, _plans, _positive_int, _user_service

    identifier = _positive_int(id_external_inventory, "id_external_inventory")
    user = _user_service().get_mongo_user(current_id_external_user())
    company = _company_id(user)
    plan = _plans().get_by_id_external_inventory(identifier)
    if plan.id_external_company != company:
        raise ValueError(
            f"Improvement plan with id_external_inventory {identifier} not found."
        )


def _chatgpt_function(
    func: Callable[..., Any],
    *,
    inject_identity: bool,
    inject_company: bool,
    check_company: bool,
) -> Callable[..., Any]:
    """Return a ChatGPT-facing function that hides id_external_user."""

    signature = inspect.signature(func)
    hidden = {"id_external_user", "id_external_company"}
    public_signature = signature.replace(
        parameters=[
            parameter
            for name, parameter in signature.parameters.items()
            if name not in hidden
        ]
    )

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        """Forward the ChatGPT call with a bound identity and company guard."""

        bound = public_signature.bind(*args, **kwargs)
        bound.apply_defaults()
        if check_company:
            _assert_plan_belongs_to_user_company(bound.arguments["id_external_inventory"])
        call_kwargs = dict(kwargs)
        if inject_identity:
            call_kwargs["id_external_user"] = current_id_external_user()
        if inject_company:
            call_kwargs["id_external_company"] = current_id_external_company()
        return func(*args, **call_kwargs)

    wrapper.__signature__ = public_signature
    return wrapper


def _wrap_chatgpt_tool(tool: Tool) -> Tool:
    """Wrap one catalog tool for ChatGPT, leaving anonymous tools unchanged."""

    from cmd.api.acl.open_ai.catalog import ANONYMOUS_CHATGPT_TOOL_NAMES
    from cmd.api.tools.constants import CHATGPT_ANALYZE_INVENTORY_DESCRIPTION
    from cmd.api.tools.inventory_tools import _analyze_inventory_chatgpt

    if tool.name in ANONYMOUS_CHATGPT_TOOL_NAMES:
        return tool

    if tool.name == "analyze_inventory":
        return Tool(
            name=tool.name,
            description=CHATGPT_ANALYZE_INVENTORY_DESCRIPTION,
            func=_analyze_inventory_chatgpt,
            args_schema=create_schema_from_function(
                tool.name, _analyze_inventory_chatgpt
            ),
        )

    func = tool.func
    signature = inspect.signature(func)
    inject_identity = "id_external_user" in signature.parameters
    inject_company = "id_external_company" in signature.parameters
    check_company = tool.name in _COMPANY_CHECKED_PLAN_TOOLS
    if not inject_identity and not inject_company and not check_company:
        return tool

    wrapped = _chatgpt_function(
        func,
        inject_identity=inject_identity,
        inject_company=inject_company,
        check_company=check_company,
    )
    
    return Tool(
        name=tool.name,
        description=_strip_identity_from_description(tool.description),
        func=wrapped,
        args_schema=create_schema_from_function(tool.name, wrapped),
    )
