"""Mypy plugin entry point for literal ``object.__setattr__`` assignments (plus matching ``setattr`` hooks)."""

from collections.abc import Callable
from dataclasses import InitVar, dataclass, field
from typing import Final, override

from mypy.nodes import Expression, StrExpr, SymbolTableNode, TypeInfo, Var
from mypy.plugin import FunctionContext, MethodContext, Plugin
from mypy.subtypes import is_subtype
from mypy.types import Instance, Type, get_proper_type


class SetattrPlugin(Plugin):
    """Register hooks that validate literal ``object.__setattr__`` usage (and mirror them for ``setattr``)."""

    @override
    def get_function_hook(self, fullname: str) -> Callable[[FunctionContext], Type] | None:
        match fullname:
            case "builtins.setattr":
                return setattr_hook
            case _:
                return super().get_function_hook(fullname)

    @override
    def get_method_hook(self, fullname: str) -> Callable[[MethodContext], Type] | None:
        match fullname:
            case "builtins.object.__setattr__":
                return setattr_hook
            case _:
                return super().get_method_hook(fullname)


def setattr_hook(ctx: FunctionContext | MethodContext) -> Type:
    """Validate literal attribute assignments routed through ``object.__setattr__`` (and ``setattr`` for parity).

    Args:
        ctx: Callback context provided by mypy for the function or method call.

    Returns:
        Type: The default return type supplied by mypy for the call site.

    """
    try:
        function_context: Final = SetattrFunctionContext(ctx)
    except ValueError as e:  # Wrong usage of setattr
        ctx.api.fail(e.args[0], ctx.context)
        return ctx.default_return_type

    literal_name_attr: Final = function_context.ensure_literal_name_attribute()
    if literal_name_attr is None:  # When setattr is called with non-literal name, this plugin do nothing
        return ctx.default_return_type

    result: Final = literal_name_attr.check_type()
    if isinstance(result, LiteralNameAttributeTypeCheckResultPassed):
        return ctx.default_return_type

    error_message: Final = LiteralNameAttributeTypeCheckResultErrorHandler(
        error=result,
    ).message()
    ctx.api.fail(error_message, ctx.context)

    return ctx.default_return_type


@dataclass(frozen=True)
class TypeInfoWrapper:
    """Expose attribute lookups across the entire MRO for a ``TypeInfo``."""

    info: TypeInfo

    def by_name(self, name: str) -> SymbolTableNode | None:
        """Return the first definition for ``name`` in the wrapped type hierarchy.

        Args:
            name: Attribute name to resolve on the wrapped ``TypeInfo``.

        Returns:
            SymbolTableNode | None: The matching symbol, if one exists.

        """
        root_node: Final = self.info.names.get(name)
        if root_node is not None:
            return root_node

        for parent in self.info.mro:
            parent_node = parent.names.get(name)
            if parent_node is not None:
                return parent_node

        return None


@dataclass(frozen=True)
class LiteralNameAttributeTypeCheckResultPassed:
    """Marker indicating the attribute assignment is valid."""


@dataclass(frozen=True)
class LiteralNameAttributeTypeCheckResultAttributeDoesNotExist:
    """Report that the attribute name is not defined on the type."""

    name: str
    obj_type: Instance


@dataclass(frozen=True)
class LiteralNameAttributeTypeCheckResultSymbolIsNotVariable:
    """Report that the resolved symbol is not a data attribute."""

    name: str
    obj_type: Instance


@dataclass(frozen=True)
class LiteralNameAttributeTypeCheckResultSymbolNodeTypeIsNone:
    """Report that the attribute lacks type information."""

    name: str
    obj_type: Instance


@dataclass(frozen=True)
class LiteralNameAttributeTypeCheckResultDoesNotSatisfyType:
    """Report a type mismatch between the assigned value and annotation."""

    name: str
    obj_type: Instance
    expected: Type
    actual: Type


type LiteralNameAttributeTypeCheckResultFailed = (
    LiteralNameAttributeTypeCheckResultAttributeDoesNotExist
    | LiteralNameAttributeTypeCheckResultSymbolIsNotVariable
    | LiteralNameAttributeTypeCheckResultSymbolNodeTypeIsNone
    | LiteralNameAttributeTypeCheckResultDoesNotSatisfyType
)

type LiteralNameAttributeTypeCheckResult = (
    LiteralNameAttributeTypeCheckResultPassed | LiteralNameAttributeTypeCheckResultFailed
)


@dataclass(frozen=True)
class TypeDisplayFormatter:
    """Format mypy types and instances for error messages."""

    instance: Instance

    def display_string(self) -> str:
        """Produce display text for an ``Instance`` with a graceful fallback."""
        display: Final = str(self.instance)
        if display:
            return display
        # Fallback to the fully-qualified name when mypy omits readable text.
        fullname: Final = self.instance.type.fullname
        return fullname or self.instance.type.name


@dataclass(frozen=True)
class LiteralNameAttributeTypeCheckResultErrorHandler:
    """Render user-friendly diagnostics for literal attribute failures."""

    error: LiteralNameAttributeTypeCheckResultFailed

    def message(self) -> str:
        """Return the formatted failure message.

        Returns:
            str: Human-readable error message describing the failure reason.

        """
        formatter: Final = TypeDisplayFormatter(self.error.obj_type)
        obj_display: Final = formatter.display_string()
        match self.error:
            case LiteralNameAttributeTypeCheckResultAttributeDoesNotExist():
                return f'attribute "{self.error.name}" does not exist on {obj_display}'
            case LiteralNameAttributeTypeCheckResultSymbolIsNotVariable():
                return f'attribute "{self.error.name}" on {obj_display} is not a data attribute'
            case LiteralNameAttributeTypeCheckResultSymbolNodeTypeIsNone():
                return f'attribute "{self.error.name}" on {obj_display} has no inferred type'
            case LiteralNameAttributeTypeCheckResultDoesNotSatisfyType():
                actual = str(self.error.actual)
                expected = str(self.error.expected)
                return (
                    f'value of type "{actual}" is not assignable to attribute "{self.error.name}" '
                    f'on {obj_display}; expected "{expected}"'
                )


@dataclass(frozen=True)
class SetattrFunctionContextLiteralNameAttribute:
    """Bundle details about a literal-string attribute assignment driven by ``object.__setattr__``."""

    name: str
    obj_type: Instance
    value_type: Type

    def check_type(self) -> LiteralNameAttributeTypeCheckResult:
        """Validate that the named attribute exists and accepts the provided value type.

        Returns:
            LiteralNameAttributeTypeCheckResult: Result representing the validation outcome.

        """
        info: Final = TypeInfoWrapper(self.obj_type.type)
        symbol: Final = info.by_name(self.name)
        if symbol is None:
            return LiteralNameAttributeTypeCheckResultAttributeDoesNotExist(self.name, self.obj_type)
        if not isinstance(symbol.node, Var):
            return LiteralNameAttributeTypeCheckResultSymbolIsNotVariable(self.name, self.obj_type)
        if symbol.node.type is None:
            return LiteralNameAttributeTypeCheckResultSymbolNodeTypeIsNone(self.name, self.obj_type)

        attribute_proper_type: Final = get_proper_type(symbol.node.type)
        value_proper_type: Final = get_proper_type(self.value_type)
        if not is_subtype(value_proper_type, attribute_proper_type):
            return LiteralNameAttributeTypeCheckResultDoesNotSatisfyType(
                self.name,
                self.obj_type,
                expected=attribute_proper_type,
                actual=value_proper_type,
            )

        return LiteralNameAttributeTypeCheckResultPassed()


class WrongNumberOfArgumentError(ValueError):
    """Raised when the hook observes an unexpected ``object.__setattr__``/``setattr`` signature."""

    def __init__(self) -> None:
        """Initialise the base ``ValueError`` with a user-friendly message."""
        super().__init__("object.__setattr__/setattr takes the wrong number of arguments.")


@dataclass(frozen=True)
class SetattrFunctionContext:
    """Normalise hook parameters from mypy's ``object.__setattr__`` callback (and its ``setattr`` twin)."""

    name: Expression = field(init=False)
    obj_type: Type = field(init=False)
    name_type: Type = field(init=False)
    value_type: Type = field(init=False)

    ctx: InitVar[FunctionContext | MethodContext]

    def __post_init__(self, ctx: FunctionContext | MethodContext) -> None:
        """Extract positional and type information from the hook arguments.

        Args:
            ctx: Callback context containing the call arguments and inferred types.

        """
        match ctx.args:
            case [[_obj], [name], [_value]]:
                object.__setattr__(self, "name", name)
            case _:
                raise WrongNumberOfArgumentError

        match ctx.arg_types:
            case [[obj_type], [name_type], [value_type]]:
                object.__setattr__(self, "obj_type", obj_type)
                object.__setattr__(self, "name_type", name_type)
                object.__setattr__(self, "value_type", value_type)
            case _:
                # It does not seems to occur because firstly the exception is raised in "match ctx.args".
                raise WrongNumberOfArgumentError

    def ensure_literal_name_attribute(self) -> SetattrFunctionContextLiteralNameAttribute | None:
        """Return the literal attribute assignment when both name and receiver are statically known.

        Returns:
            SetattrFunctionContextLiteralNameAttribute | None: Normalised literal assignment data, if available.

        """
        match (self.name, self.obj_type):
            case (StrExpr() as name, Instance() as obj_type):
                return SetattrFunctionContextLiteralNameAttribute(
                    name=name.value, obj_type=obj_type, value_type=self.value_type
                )
            case _:
                return None


def plugin(_version: str) -> type[Plugin]:
    """Return the plugin entry point consumed by mypy.

    Args:
        _version: Version string provided by mypy during plugin registration.

    Returns:
        type[Plugin]: The plugin class to register.

    """
    return SetattrPlugin
