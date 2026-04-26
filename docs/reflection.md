# AI Tools Used

Claude (Anthropic) was used as a development assistant during this build, for:

- Folder structure scaffolding and `requirements.txt` generation.
- Writing Pydantic input schemas alongside their corresponding Gemini `FunctionDeclaration`s so the two definitions stayed in sync.
- Diagnosing an EIA API response quirk in which crude oil rows are returned twice per period — once in MBBL (monthly total) and once in MBBL/D (daily average). The unit-filter fix is in [`src/data/loader.py`](../src/data/loader.py).
- Drafting test cases for each module alongside the code under test.
- Initial drafts of the documentation files in `docs/` for human review.

API keys were never visible to the AI assistant. They live in `.streamlit/secrets.toml` (gitignored) locally, and in Streamlit Cloud's secrets manager in production.
