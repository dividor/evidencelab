# Project Rules

## Git Commits
- **NEVER use `--no-verify` when committing.** If a pre-commit hook fails, ALWAYS fix the underlying issue (lint errors, formatting, complexity, etc.) before committing again. No exceptions.

## Code Quality
- **NEVER use `noqa`, `type: ignore`, or similar suppressions to bypass pre-commit hooks or linters.** Fix the actual issue instead. Only use suppressions if explicitly requested by the user.
- **NEVER code fallbacks or graceful degradation unless explicitly requested.** If a dependency or feature is required, fail hard and loud. Silent fallbacks hide bugs.

## Testing
- **All new features and functions MUST have associated unit tests.** Write tests in `tests/unit/` following existing patterns (pytest, mocking with `unittest.mock`).
