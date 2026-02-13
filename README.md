# mypy-setattr

`mypy-setattr` is a mypy plugin for literal-name assignments via `object.__setattr__` (and `setattr`).
It checks that the target attribute exists and that the assigned value matches the declared type.
It reports mypy errors for unknown attributes and incompatible value types.
The main use case is `__post_init__` in frozen dataclasses.

```python
# example.py
from dataclasses import dataclass, field

@dataclass(frozen=True)
class User:
    name: str
    slug: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "slug", self.name.lower())  # OK
        object.__setattr__(self, "slgu", self.name.lower())  # typo: unknown attribute
        object.__setattr__(self, "slug", 123)  # wrong type: expected str
```

```text
$ uv run mypy --config-file pyproject.toml example.py
example.py:10: error: attribute "slgu" does not exist on example.User  [misc]
example.py:11: error: value of type "Literal[123]?" is not assignable to attribute "slug" on example.User; expected "builtins.str"  [misc]
Found 2 errors in 1 file (checked 1 source file)
```

## Motivation

The standard mypy type checker cannot reason about dynamic attribute names, so `object.__setattr__`
and `setattr` calls silently bypass attribute existence checks and value type validation. Projects that
lean on frozen dataclasses, `__setattr__` overrides, or metaprogramming end up trading
runtime correctness for static flexibility. This plugin restores that safety by enforcing
lookups when the attribute name is a literal string: assignments to `Any`-typed attributes
remain permissive, while every other annotated type (whether `int`, `dict[str, str]`, or
`Literal["aaa", "bbb"]`) is validated. As a result, teams can keep expressive initialisation
patterns without losing coverage from their type checker or relying on fragile helper wrappers.
Whether you call `object.__setattr__` or use plain `setattr`, the same literal-name guarantees
apply—with the object variant remaining the main monitored surface.

## Usage

1. Install the package in the environment that runs mypy.
2. Enable the plugin in your `mypy.ini` or `pyproject.toml`:

   ```ini
   # mypy.ini
   [mypy]
   plugins = mypy_setattr.plugin
   ```

    ```toml
    # pyproject.toml
    [tool.mypy]
    plugins = ["mypy_setattr.plugin"]

    ```
3. Call `object.__setattr__` inside frozen dataclasses whenever you want literal-name type checking—the plugin adds the
   safety checks automatically. Plain `setattr` enjoys the same enforcement if you happen to use it.

#### Example: frozen dataclass

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class User:
    name: str
    slug: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "slug", self.name.lower())


def make_user(raw_name: str) -> User:
    return User(raw_name)
```
When mypy runs with the plugin enabled, it verifies the `"slug"` assignment is allowed and that the value type
matches the annotated attribute.

## Development

- Formatting: `./scripts/format.sh`
- Format check (CI-safe): `./scripts/format-dry-run.sh`
- Linting: `./scripts/lint.sh`
- Tests: `./scripts/test.sh`
- Type checks: `./scripts/typecheck.sh`

### Guix environment helpers

- `manifest.scm` lists the packages required to work on this repository via GNU Guix.
- `channels.scm` pins the Guix channel revisions used for reproducible environments.
- `guix-shell.sh` drops you into a development shell defined by `manifest.scm`.
  This is fast but it is not reproducible, because guix channel is not pinned.
  ```
  # Add extra manifest files or packages
  ./guix-shell.sh -m path/to/extra-manifest.scm python

  # Run a single command inside the environment
  ./guix-shell.sh -- ./scripts/typecheck.sh
  ```
- `guix-time-machine-shell.sh` does the same, but first time-travels to the pinned channels from `channels.scm`.
  This command is too late to run frequently, but completely reproducible.
  ```
  # Time-machine shell with additional dependencies
  ./guix-time-machine-shell.sh -m aux-manifest.scm mypy

  # One-shot execution against the pinned channels
  ./guix-time-machine-shell.sh -- ./scripts/typecheck.sh
  ```

## License

This project is released under the [GNU Affero General Public License v3.0](LICENSE). Using `mypy-setattr`
as a development-only dependency—for example, to improve type checking in CI—does not infect your product or
runtime artifacts with AGPL obligations; the copyleft terms apply to the plugin itself and any modifications
you make to it. If you embed the plugin directly into a distributed product, ensure that distribution complies
with AGPL-3.0.
