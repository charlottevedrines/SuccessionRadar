# Succession Radar

Prototype AI pipeline that helps spot small French IT services companies (ESNs) that may be up for sale, by looking for ownership and leadership signals in public registries.

> **Status: work in progress.** Started during the X-IA hackathon (September 2026) by a team of five. This is a prototype: there is no automated test suite or evaluation set yet, and the scope is deliberately narrow (French ESNs, 10 companies per discovery run).

## Why

Small ESNs (10 to 50 employees) are an active M&A segment in France. A typical sale candidate has a founder-CEO late in their career, no co-manager and no identified successor, and sometimes a newly created holding company. Private equity funds and brokers mostly find these companies by cold-calling; this project explores automating the first screening step.

## How it works

```text
interface.py --> selections.json --> discovery.py --> matched_companies.json --> Ownership agent --> holding_results.json
 (Streamlit)      (region, size)      (ESN search)      (SIREN + name)
```

| Component | What it does |
|---|---|
| `interface.py` | Streamlit form to choose a region and an employee band. Saves `selections.json`. |
| `discovery.py` | Queries the public [recherche-entreprises](https://recherche-entreprises.api.gouv.fr) API for ESNs matching the filters. Limited to 10 companies while prototyping. Writes `matched_companies.json`. |
| `tools/ownership/detecter_holding.py` | **Ownership agent**: detects whether a new holding company was created to hold the target's shares (details below). Writes `tools/ownership/holding_results.json`. |
| `tools/ownership/detecter_holding_evenements.py` | Variant of the Ownership agent organised around events (securities transactions). Writes `tools/ownership/holding_events_results.json`. |
| `Leadership tool/` | Standalone tool that enriches companies with officers' ages and estimated tenure, from public company data and BODACC announcements. Has its own input file (see `input_test.json`). |

### Ownership agent

For each company in `matched_companies.json`:

1. Downloads the company's filed deeds (PDF) from the INPI national company registry (RNE) API and extracts their text with `pypdf`.
2. Splits the text into overlapping passages and ranks them with a keyword heuristic. Keywords only decide what to read first; they are never used as proof.
3. Asks a local LLM (Llama 3.1 8B through [Ollama](https://ollama.com); override with the `OLLAMA_MODEL` variable) to answer in JSON. Ollama's `format` parameter enforces a JSON schema, so the expected fields are always present.
4. If evidence is missing, runs up to two follow-up searches in other passages.
5. Checks that every quoted piece of evidence appears word for word in the source passage. A citation that cannot be found is not accepted as proof.

Each company ends with a status (`oui`, `peut_etre`, `non_detecte`, `texte_insuffisant` or `erreur`), together with the evidence, alerts and per-passage analyses, so that a human can review every decision.

The schema guarantees the shape of the answer, not its correctness: the LLM extracts and classifies, and plain code checks the evidence.

## Run it

Requirements: Python 3.11, [Ollama](https://ollama.com) running locally, and an account on the INPI RNE API.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Choose filters, then click "Save selections"
streamlit run interface.py

# 2. Find candidate ESNs (writes matched_companies.json)
python discovery.py

# 3. Ownership agent
ollama pull llama3.1:8b
export INPI_USERNAME="your-inpi-email"
export INPI_PASSWORD="your-inpi-password"
python tools/ownership/detecter_holding.py
```

Instead of environment variables you can create `tools/ownership/config_inpi.json` with `{"email": "...", "mot_de_passe": "..."}`; this file is git-ignored. If neither is set, the script asks for the credentials in the terminal.

By default `SIREN_TEST` (top of the script) restricts a run to a single test company. Set it to an empty string to process every company in `matched_companies.json`.

Leadership tool:

```bash
cd "Leadership tool"
python run.py input_test.json output.json
```

## Known limitations

- No tests and no evaluation set yet: the accuracy of the LLM judgments has not been measured.
- OCR is not implemented. Scanned deeds without a text layer cannot be read; the script only warns that OCR may be needed.
- Scope is hardcoded: French ESNs only, and discovery stops at 10 companies.
- Scripts are configured through constants at the top of each file rather than command-line arguments.
- Outputs contain names of company officers. They come from public registries but are personal data, so generated files are git-ignored and should not be committed.

## Contributions

Team project (5 people). In this repository, `interface.py`, `discovery.py` and `tools/ownership/` were written by Charlotte Védrines; `Leadership tool/` was written by other team members (see `git log`).
