from typing import Any, Callable

from .schemas import BoundTool, ToolDefinition


def agent_tool(*, name: str | None = None, description: str | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(
            func,
            "_lumibot_agent_tool",
            {
                "name": name or func.__name__,
                "description": description or (func.__doc__ or "").strip() or func.__name__,
            },
        )
        return func

    return decorator


def is_agent_tool(value: Any) -> bool:
    return hasattr(value, "_lumibot_agent_tool")


def bind_callable_tool(callable_obj: Callable[..., Any]) -> ToolDefinition:
    metadata = getattr(callable_obj, "_lumibot_agent_tool", None) or {}
    tool_name = metadata.get("name") or getattr(callable_obj, "__name__", "tool")
    description = metadata.get("description") or (getattr(callable_obj, "__doc__", "") or "").strip() or tool_name

    def binder(strategy: Any, manager: Any) -> BoundTool:
        return BoundTool(
            name=tool_name,
            description=description,
            function=callable_obj,
            source="local",
            metadata={"kind": "callable"},
        )

    return ToolDefinition(
        name=tool_name,
        description=description,
        binder=binder,
        metadata={"kind": "callable"},
    )
