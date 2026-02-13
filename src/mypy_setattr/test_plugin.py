from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING, Final, cast

import pytest
from mypy import build
from mypy.api import run as run_mypy
from mypy.modulefinder import BuildSource
from mypy.nodes import Expression, NameExpr, StrExpr, TypeInfo, Var
from mypy.options import Options
from mypy.types import Instance, NoneType
from mypy.types import Type as MypyType

from mypy_setattr.plugin import (
    LiteralNameAttributeTypeCheckResultAttributeDoesNotExist,
    LiteralNameAttributeTypeCheckResultDoesNotSatisfyType,
    LiteralNameAttributeTypeCheckResultErrorHandler,
    LiteralNameAttributeTypeCheckResultPassed,
    LiteralNameAttributeTypeCheckResultSymbolIsNotVariable,
    LiteralNameAttributeTypeCheckResultSymbolNodeTypeIsNone,
    SetattrFunctionContext,
    SetattrFunctionContextLiteralNameAttribute,
    TypeDisplayFormatter,
    TypeInfoWrapper,
    WrongNumberOfArgumentError,
)

if TYPE_CHECKING:
    from mypy.plugin import FunctionContext, MethodContext

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def write_sample(tmp_path: Path, code: str) -> Path:
    path = tmp_path / "sample.py"
    path.write_text(dedent(code))
    return path


def write_config(tmp_path: Path) -> Path:
    config = tmp_path / "mypy.ini"
    config.write_text(
        dedent(
            """
            [mypy]
            plugins = mypy_setattr.plugin
            show_traceback = true
            """,
        ).lstrip(),
    )
    return config


def run_with_plugin(tmp_path: Path, code: str) -> tuple[str, str, int]:
    sample_path = write_sample(tmp_path, code)
    config_path = write_config(tmp_path)
    return run_mypy(["--config-file", str(config_path), str(sample_path)])


def assert_mypy_result(
    tmp_path: Path,
    code: str,
    *,
    expected_exit: int,
    expected_stdout_substring: str | None = None,
) -> tuple[str, str]:
    stdout, stderr, exit_code = run_with_plugin(tmp_path, code)
    assert exit_code == expected_exit, stdout + stderr
    if expected_stdout_substring is not None:
        assert expected_stdout_substring in stdout
    return stdout, stderr


def build_type_environment(code: str) -> tuple[dict[str, TypeInfo], dict[str, TypeInfo]]:
    options = Options()
    options.incremental = False
    options.show_traceback = True
    build_result = build.build([BuildSource(None, "__main__", dedent(code))], options)
    module_state = build_result.graph["__main__"]
    assert module_state.tree is not None
    module_type_infos: dict[str, TypeInfo] = {}
    for name, symbol in module_state.tree.names.items():
        if isinstance(symbol.node, TypeInfo):
            module_type_infos[name] = symbol.node

    builtins_state = build_result.graph["builtins"]
    assert builtins_state.tree is not None
    builtin_type_infos: dict[str, TypeInfo] = {}
    for name, symbol in builtins_state.tree.names.items():
        if isinstance(symbol.node, TypeInfo):
            builtin_type_infos[name] = symbol.node

    return module_type_infos, builtin_type_infos


def instance(info: TypeInfo) -> Instance:
    return Instance(info, [])


def _as_plugin_context(obj: object) -> FunctionContext | MethodContext:
    return cast("FunctionContext | MethodContext", obj)


class TestObjectSetattr:
    class TestKnownAttributeAssignments:
        class TestNormalClass:
            def test_correct_literal_attribute_assignment(self, tmp_path: Path) -> None:
                assert_mypy_result(
                    tmp_path,
                    """
                    class User:
                        name: str

                    def update(user: User) -> None:
                        object.__setattr__(user, "name", "Bob")
                    """,
                    expected_exit=0,
                )

            def test_wrong_literal_attribute_assignment(self, tmp_path: Path) -> None:
                assert_mypy_result(
                    tmp_path,
                    """
                    class User:
                        name: str

                    def update(user: User) -> None:
                        object.__setattr__(user, "name", 1)
                    """,
                    expected_exit=1,
                    expected_stdout_substring='attribute "name"',
                )

            def test_optional_value_assignment(self, tmp_path: Path) -> None:
                assert_mypy_result(
                    tmp_path,
                    """
                    class User:
                        nickname: str | None

                    def update(user: User) -> None:
                        object.__setattr__(user, "nickname", None)
                    """,
                    expected_exit=0,
                )

        class TestInheritedClass:
            def test_correct_attribute_assignment_from_second_base(self, tmp_path: Path) -> None:
                assert_mypy_result(
                    tmp_path,
                    """
                    class Named:
                        name: str

                    class Timestamped:
                        created_at: int

                    class User(Named, Timestamped):
                        pass

                    def update(user: User) -> None:
                        object.__setattr__(user, "created_at", 11)
                    """,
                    expected_exit=0,
                )

            def test_wrong_attribute_assignment_from_second_base(self, tmp_path: Path) -> None:
                assert_mypy_result(
                    tmp_path,
                    """
                    class Named:
                        name: str

                    class Timestamped:
                        created_at: int

                    class User(Named, Timestamped):
                        pass

                    def update(user: User) -> None:
                        object.__setattr__(user, "created_at", "oops")
                    """,
                    expected_exit=1,
                    expected_stdout_substring='attribute "created_at"',
                )

    class TestDataclassAssignments:
        class TestMutableDataclass:
            def test_correct_literal_assignment(self, tmp_path: Path) -> None:
                assert_mypy_result(
                    tmp_path,
                    """
                    from dataclasses import dataclass

                    @dataclass
                    class User:
                        name: str

                    def update(user: User) -> None:
                        object.__setattr__(user, "name", "Bob")
                    """,
                    expected_exit=0,
                )

            def test_wrong_literal_assignment(self, tmp_path: Path) -> None:
                assert_mypy_result(
                    tmp_path,
                    """
                    from dataclasses import dataclass

                    @dataclass
                    class User:
                        name: str

                    def update(user: User) -> None:
                        object.__setattr__(user, "name", 1)
                    """,
                    expected_exit=1,
                    expected_stdout_substring='attribute "name"',
                )

            def test_optional_assignment(self, tmp_path: Path) -> None:
                assert_mypy_result(
                    tmp_path,
                    """
                    from dataclasses import dataclass

                    @dataclass
                    class User:
                        nickname: str | None

                    def update(user: User) -> None:
                        object.__setattr__(user, "nickname", None)
                    """,
                    expected_exit=0,
                )

        class TestFrozenDataclassPostInit:
            def test_wrong_literal_assignment_in_post_init(self, tmp_path: Path) -> None:
                assert_mypy_result(
                    tmp_path,
                    """
                    from dataclasses import dataclass

                    @dataclass(frozen=True)
                    class User:
                        name: str

                        def __post_init__(self) -> None:
                            object.__setattr__(self, "name", 1)
                    """,
                    expected_exit=1,
                    expected_stdout_substring='attribute "name"',
                )

            def test_wrong_second_base_assignment_in_post_init(self, tmp_path: Path) -> None:
                assert_mypy_result(
                    tmp_path,
                    """
                    from dataclasses import dataclass

                    @dataclass(frozen=True)
                    class Named:
                        name: str

                    @dataclass(frozen=True)
                    class Timestamped:
                        created_at: int

                    @dataclass(frozen=True)
                    class User(Named, Timestamped):
                        def __post_init__(self) -> None:
                            object.__setattr__(self, "created_at", "oops")
                    """,
                    expected_exit=1,
                    expected_stdout_substring='attribute "created_at"',
                )

            def test_optional_assignment_in_post_init(self, tmp_path: Path) -> None:
                assert_mypy_result(
                    tmp_path,
                    """
                    from dataclasses import dataclass

                    @dataclass(frozen=True)
                    class User:
                        nickname: str | None

                        def __post_init__(self) -> None:
                            object.__setattr__(self, "nickname", None)
                    """,
                    expected_exit=0,
                )

    class TestMissingAttributes:
        def test_reports_missing_attribute(self, tmp_path: Path) -> None:
            assert_mypy_result(
                tmp_path,
                """
                class User:
                    name: str

                def update(user: User) -> None:
                    object.__setattr__(user, "age", 1)
                """,
                expected_exit=1,
                expected_stdout_substring='attribute "age"',
            )

    class TestWrongUsageOfSetattr:
        def test_reports_error_when_value_argument_is_missing(self, tmp_path: Path) -> None:
            assert_mypy_result(
                tmp_path,
                """
                class User:
                    name: str

                def update(user: User) -> None:
                    object.__setattr__(user, "name")
                """,
                expected_exit=1,
                expected_stdout_substring='Too few arguments for "__setattr__"',
            )

        def test_reports_error_when_too_many_arguments_are_passed(self, tmp_path: Path) -> None:
            assert_mypy_result(
                tmp_path,
                """
                class User:
                    name: str

                def update(user: User) -> None:
                    object.__setattr__(user, "name", "Bob", "extra")
                """,
                expected_exit=1,
                expected_stdout_substring='Too many arguments for "__setattr__"',
            )


class TestSetattr:
    class TestKnownAttributeAssignments:
        class TestNormalClass:
            def test_correct_attribute_assignment_from_class_body(self, tmp_path: Path) -> None:
                assert_mypy_result(
                    tmp_path,
                    """
                    class User:
                        name: str

                    def update(user: User) -> None:
                        setattr(user, "name", "Bob")
                    """,
                    expected_exit=0,
                )

            def test_wrong_attribute_assignment_from_class_body(self, tmp_path: Path) -> None:
                assert_mypy_result(
                    tmp_path,
                    """
                    class User:
                        name: str

                    def update(user: User) -> None:
                        setattr(user, "name", 1)
                    """,
                    expected_exit=1,
                    expected_stdout_substring='attribute "name"',
                )

            def test_optional_value_assignment(self, tmp_path: Path) -> None:
                assert_mypy_result(
                    tmp_path,
                    """
                    class User:
                        nickname: str | None

                    def update(user: User) -> None:
                        setattr(user, "nickname", None)
                    """,
                    expected_exit=0,
                )

            def test_any_typed_attribute(self, tmp_path: Path) -> None:
                assert_mypy_result(
                    tmp_path,
                    """
                    from typing import Any

                    class User:
                        data: Any

                    def update(user: User) -> None:
                        setattr(user, "data", 1)
                    """,
                    expected_exit=0,
                )

        class TestInheritedClass:
            def test_correct_attribute_assignment_from_base_class(self, tmp_path: Path) -> None:
                assert_mypy_result(
                    tmp_path,
                    """
                    class Base:
                        name: str

                    class User(Base):
                        pass

                    def update(user: User) -> None:
                        setattr(user, "name", "Bob")
                    """,
                    expected_exit=0,
                )

            def test_wrong_attribute_assignment_from_base_class(self, tmp_path: Path) -> None:
                assert_mypy_result(
                    tmp_path,
                    """
                    class Base:
                        name: str

                    class User(Base):
                        pass

                    def update(user: User) -> None:
                        setattr(user, "name", 1)
                    """,
                    expected_exit=1,
                    expected_stdout_substring='attribute "name"',
                )

            def test_correct_attribute_assignment_from_second_base(self, tmp_path: Path) -> None:
                assert_mypy_result(
                    tmp_path,
                    """
                    class Named:
                        name: str

                    class Timestamped:
                        created_at: int

                    class User(Named, Timestamped):
                        pass

                    def update(user: User) -> None:
                        setattr(user, "created_at", 11)
                    """,
                    expected_exit=0,
                )

            def test_wrong_attribute_assignment_from_second_base(self, tmp_path: Path) -> None:
                assert_mypy_result(
                    tmp_path,
                    """
                    class Named:
                        name: str

                    class Timestamped:
                        created_at: int

                    class User(Named, Timestamped):
                        pass

                    def update(user: User) -> None:
                        setattr(user, "created_at", "oops")
                    """,
                    expected_exit=1,
                    expected_stdout_substring='attribute "created_at"',
                )

        class TestDataclass:
            def test_correct_attribute_assignment_in_dataclass(self, tmp_path: Path) -> None:
                assert_mypy_result(
                    tmp_path,
                    """
                    from dataclasses import dataclass

                    @dataclass
                    class User:
                        name: str

                    def update(user: User) -> None:
                        setattr(user, "name", "Bob")
                    """,
                    expected_exit=0,
                )

            def test_wrong_attribute_assignment_in_dataclass(self, tmp_path: Path) -> None:
                assert_mypy_result(
                    tmp_path,
                    """
                    from dataclasses import dataclass

                    @dataclass
                    class User:
                        name: str

                    def update(user: User) -> None:
                        setattr(user, "name", 1)
                    """,
                    expected_exit=1,
                    expected_stdout_substring='attribute "name"',
                )

    class TestMissingAttributes:
        def test_reports_missing_attribute(self, tmp_path: Path) -> None:
            assert_mypy_result(
                tmp_path,
                """
                class User:
                    name: str

                def update(user: User) -> None:
                    setattr(user, "age", 1)
                """,
                expected_exit=1,
                expected_stdout_substring='attribute "age"',
            )

    class TestLiteralConstraints:
        def test_literal_union_assignment(self, tmp_path: Path) -> None:
            assert_mypy_result(
                tmp_path,
                """
                from typing import Literal

                class User:
                    alias: Literal["aaa", "bbb"]

                def update(user: User) -> None:
                    setattr(user, "alias", "ccc")
                """,
                expected_exit=1,
                expected_stdout_substring='attribute "alias"',
            )

        class TestDynamicAttributeName:
            def test_dynamic_attribute_name(self, tmp_path: Path) -> None:
                assert_mypy_result(
                    tmp_path,
                    """
                class User:
                    name: str

                def update(user: User, field: str) -> None:
                    setattr(user, field, 1)
                """,
                    expected_exit=0,
                )

    class TestWrongUsageOfSetattr:
        def test_reports_error_when_value_argument_is_missing(self, tmp_path: Path) -> None:
            assert_mypy_result(
                tmp_path,
                """
                class User:
                    name: str

                def update(user: User) -> None:
                    setattr(user, "name")
                """,
                expected_exit=1,
                expected_stdout_substring='Too few arguments for "setattr"',
            )

        def test_reports_error_when_too_many_arguments_are_passed(self, tmp_path: Path) -> None:
            assert_mypy_result(
                tmp_path,
                """
                class User:
                    name: str

                def update(user: User) -> None:
                    setattr(user, "name", "Bob", "extra")
                """,
                expected_exit=1,
                expected_stdout_substring='Too many arguments for "setattr"',
            )


class TestTypeInfoWrapper:
    def test_by_name_resolves_defined_attribute(self) -> None:
        module_infos, _ = build_type_environment(
            """
            class User:
                name: str
            """
        )
        wrapper = TypeInfoWrapper(module_infos["User"])
        symbol = wrapper.by_name("name")
        assert symbol is not None
        assert isinstance(symbol.node, Var)

    def test_by_name_walks_mro(self) -> None:
        module_infos, _ = build_type_environment(
            """
            class Base:
                created_at: int

            class User(Base):
                pass
            """
        )
        wrapper = TypeInfoWrapper(module_infos["User"])
        symbol = wrapper.by_name("created_at")
        assert symbol is not None
        assert isinstance(symbol.node, Var)

    def test_by_name_returns_none_when_missing(self) -> None:
        module_infos, _ = build_type_environment(
            """
            class User:
                name: str
            """
        )
        wrapper = TypeInfoWrapper(module_infos["User"])
        assert wrapper.by_name("missing") is None


class TestLiteralNameAttributeTypeCheckResultErrorHandler:
    def test_reports_missing_attribute(self) -> None:
        module_infos, _ = build_type_environment(
            """
            class User:
                name: str
            """
        )
        user_instance = instance(module_infos["User"])
        handler = LiteralNameAttributeTypeCheckResultErrorHandler(
            error=LiteralNameAttributeTypeCheckResultAttributeDoesNotExist("missing", user_instance),
        )
        assert handler.message() == 'attribute "missing" does not exist on __main__.User'

    def test_reports_symbol_not_variable(self) -> None:
        module_infos, _ = build_type_environment(
            """
            class User:
                name: str

                def rename(self) -> None:
                    ...
            """
        )
        user_instance = instance(module_infos["User"])
        handler = LiteralNameAttributeTypeCheckResultErrorHandler(
            error=LiteralNameAttributeTypeCheckResultSymbolIsNotVariable("rename", user_instance),
        )
        assert handler.message() == 'attribute "rename" on __main__.User is not a data attribute'

    def test_reports_attribute_without_type(self) -> None:
        module_infos, _ = build_type_environment(
            """
            class User:
                name: str
            """
        )
        user_info = module_infos["User"]
        var = user_info.names["name"].node
        assert isinstance(var, Var)
        var.type = None

        user_instance = instance(user_info)
        handler = LiteralNameAttributeTypeCheckResultErrorHandler(
            error=LiteralNameAttributeTypeCheckResultSymbolNodeTypeIsNone("name", user_instance),
        )
        assert handler.message() == 'attribute "name" on __main__.User has no inferred type'

    def test_reports_type_mismatch(self) -> None:
        module_infos, builtin_infos = build_type_environment(
            """
            class User:
                name: str
            """
        )
        user_instance = instance(module_infos["User"])
        handler = LiteralNameAttributeTypeCheckResultErrorHandler(
            error=LiteralNameAttributeTypeCheckResultDoesNotSatisfyType(
                "name",
                user_instance,
                expected=instance(builtin_infos["str"]),
                actual=instance(builtin_infos["int"]),
            ),
        )
        expected_message = (
            'value of type "builtins.int" is not assignable to attribute "name" '
            'on __main__.User; expected "builtins.str"'
        )
        assert handler.message() == expected_message


class TestSetattrFunctionContextLiteralNameAttribute:
    def test_check_type_succeeds_for_matching_assignment(self) -> None:
        module_infos, builtin_infos = build_type_environment(
            """
            class User:
                name: str
            """
        )
        attribute = SetattrFunctionContextLiteralNameAttribute(
            name="name",
            obj_type=instance(module_infos["User"]),
            value_type=instance(builtin_infos["str"]),
        )

        assert isinstance(attribute.check_type(), LiteralNameAttributeTypeCheckResultPassed)

    def test_check_type_reports_missing_attribute(self) -> None:
        module_infos, builtin_infos = build_type_environment(
            """
            class User:
                name: str
            """
        )
        attribute = SetattrFunctionContextLiteralNameAttribute(
            name="missing",
            obj_type=instance(module_infos["User"]),
            value_type=instance(builtin_infos["str"]),
        )

        result = attribute.check_type()
        assert isinstance(result, LiteralNameAttributeTypeCheckResultAttributeDoesNotExist)

    def test_check_type_reports_symbol_that_is_not_variable(self) -> None:
        module_infos, builtin_infos = build_type_environment(
            """
            class User:
                name: str

                def rename(self) -> None:
                    ...
            """
        )
        attribute = SetattrFunctionContextLiteralNameAttribute(
            name="rename",
            obj_type=instance(module_infos["User"]),
            value_type=instance(builtin_infos["str"]),
        )

        result = attribute.check_type()
        assert isinstance(result, LiteralNameAttributeTypeCheckResultSymbolIsNotVariable)

    def test_check_type_reports_attribute_without_type_information(self) -> None:
        module_infos, builtin_infos = build_type_environment(
            """
            class User:
                name: str
            """
        )
        user_info = module_infos["User"]
        var = user_info.names["name"].node
        assert isinstance(var, Var)
        var.type = None

        attribute = SetattrFunctionContextLiteralNameAttribute(
            name="name",
            obj_type=instance(user_info),
            value_type=instance(builtin_infos["str"]),
        )

        result = attribute.check_type()
        assert isinstance(result, LiteralNameAttributeTypeCheckResultSymbolNodeTypeIsNone)

    def test_check_type_reports_type_mismatch(self) -> None:
        module_infos, builtin_infos = build_type_environment(
            """
            class User:
                name: str
            """
        )
        attribute = SetattrFunctionContextLiteralNameAttribute(
            name="name",
            obj_type=instance(module_infos["User"]),
            value_type=instance(builtin_infos["int"]),
        )

        result = attribute.check_type()
        assert isinstance(result, LiteralNameAttributeTypeCheckResultDoesNotSatisfyType)


class _DummyContext:
    def __init__(self, args: list[list[Expression]], arg_types: list[list[MypyType]]) -> None:
        self.args = args
        self.arg_types = arg_types


class TestSetattrFunctionContext:
    def test_literal_name_attribute_is_returned(self) -> None:
        module_infos, builtin_infos = build_type_environment(
            """
            class User:
                name: str
            """
        )
        ctx = _DummyContext(
            args=[
                [NameExpr("user")],
                [StrExpr("name")],
                [NameExpr("value")],
            ],
            arg_types=[
                [instance(module_infos["User"])],
                [instance(builtin_infos["str"])],
                [instance(builtin_infos["str"])],
            ],
        )

        context = SetattrFunctionContext(_as_plugin_context(ctx))
        literal = context.ensure_literal_name_attribute()
        assert literal is not None
        assert literal.name == "name"
        assert literal.obj_type.type.fullname == "__main__.User"

    def test_returns_none_for_non_literal_attribute_names(self) -> None:
        module_infos, builtin_infos = build_type_environment(
            """
            class User:
                name: str
            """
        )
        ctx = _DummyContext(
            args=[
                [NameExpr("user")],
                [NameExpr("field")],
                [NameExpr("value")],
            ],
            arg_types=[
                [instance(module_infos["User"])],
                [instance(builtin_infos["str"])],
                [instance(builtin_infos["str"])],
            ],
        )

        context = SetattrFunctionContext(_as_plugin_context(ctx))
        assert context.ensure_literal_name_attribute() is None

    def test_returns_none_when_object_type_is_not_instance(self) -> None:
        ctx = _DummyContext(
            args=[
                [NameExpr("user")],
                [StrExpr("name")],
                [NameExpr("value")],
            ],
            arg_types=[
                [NoneType()],
                [NoneType()],
                [NoneType()],
            ],
        )

        context = SetattrFunctionContext(_as_plugin_context(ctx))
        assert context.ensure_literal_name_attribute() is None

    def test_raises_when_arguments_do_not_match_expected_shape(self) -> None:
        ctx = _DummyContext(
            args=[[NameExpr("user")], [StrExpr("name")]],
            arg_types=[[NoneType()], [NoneType()]],
        )

        with pytest.raises(WrongNumberOfArgumentError):
            SetattrFunctionContext(_as_plugin_context(ctx))


class TestTypeDisplayFormatter:
    def test_display_string_returns_instance_str(self) -> None:
        module_types, _ = build_type_environment(
            """
            class Foo: ...
            """,
        )
        foo_instance = instance(module_types["Foo"])
        formatter = TypeDisplayFormatter(foo_instance)
        assert formatter.display_string() == str(foo_instance)

    def test_display_string_falls_back_to_fullname(self) -> None:
        class DummyFullname:
            fullname = "dummy.Full"
            name = "Full"

        class DummyInstance:
            type = DummyFullname()

            def __str__(self) -> str:
                return ""

        dummy = DummyInstance()
        formatter = TypeDisplayFormatter(dummy)  # type: ignore[arg-type]  # DummyInstance mimics Instance for fallback behaviour
        assert formatter.display_string() == "dummy.Full"

    def test_raises_when_too_many_arguments_are_provided(self) -> None:
        ctx = _DummyContext(
            args=[
                [NameExpr("user")],
                [StrExpr("name")],
                [NameExpr("value")],
                [NameExpr("extra")],
            ],
            arg_types=[
                [NoneType()],
                [NoneType()],
                [NoneType()],
                [NoneType()],
            ],
        )

        with pytest.raises(WrongNumberOfArgumentError):
            SetattrFunctionContext(_as_plugin_context(ctx))
