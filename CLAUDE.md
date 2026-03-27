# Project Rules

## Git Commits
- **NEVER use `--no-verify` when committing.** If a pre-commit hook fails, ALWAYS fix the underlying issue (lint errors, formatting, complexity, etc.) before committing again. No exceptions.

## Testing
- **All new features and functions MUST have associated unit tests.** Write tests in `tests/unit/` following existing patterns (pytest, mocking with `unittest.mock`).
