# mypy_setattr
Mypy plugin entry-point for ``object.__setattr__`` and `setattr` type checking.
Mainly used in `__post_init__` in frozen dataclass.

## Package Manager
- Use `uv`

## Check
- scripts/format-dry-run.sh
- scripts/lint.sh
- scripts/typecheck.sh

## Test
- scripts/test.sh

## Coding Guidelines
- Every `# type: ignore[...]` comment must include a brief justification explaining why the suppression is required.
- Prefer annotating variables with `Final` whenever possible, and omit explicit type parameters on `Final` unless necessary.
- Every pull request must update `CHANGELOG.md` with a short entry describing the change.
