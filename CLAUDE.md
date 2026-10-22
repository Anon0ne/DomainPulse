# Working on Domain Pulse

## Commits and credit

- Every commit is authored by **Anon0ne** (`Anon0ne <41264521+Anon0ne@users.noreply.github.com>`). Set this in the local git config before committing.
- Do not add `Co-Authored-By` or other Claude trailers to commit messages.
- Claude may credit itself in pull request descriptions only.
- Changes go through pull requests rather than direct pushes to `main`.

## Project notes

- Run tests with `python -m pytest`.
- Releases: run the "Build and release" workflow with a version like `v0.1.2-alpha` (tag pushes may be blocked from automated sessions, and the workflow creates the tag itself).
- Brand constants (`BRAND_URL`, `REGISTER_URL`) live in `domain_pulse/__init__.py`; colors live in `domain_pulse/theme.py`.
