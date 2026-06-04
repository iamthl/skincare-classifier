# Skincare Routine Classifier

A rule-based Python component that takes a user profile and returns a personalised skincare routine. Exposed as an HTTP API, a CLI, and a importable library.

## Project structure

```
src/
  component.py   # core classifier logic
  api.py         # Flask HTTP API
  cli.py         # command-line interface
tests/           # pytest + hypothesis test suite
Dockerfile       # multi-stage production image
Jenkinsfile      # CI/CD pipeline (lint -> type-check -> security -> test -> build -> deploy)
```

## Running locally

**Install dependencies**
```bash
pip install -r requirements.txt
```

**HTTP API**
```bash
waitress-serve --host=0.0.0.0 --port=8000 src.api:app
```

**CLI**
```bash
echo '{"skin_type":"oily","age":25,"concerns":["acne"],"climate":"humid","budget":"medium","routine_preference":"balanced","sensitivities":[]}' \
  | python -m src.cli --pretty
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/recommend` | Generate a routine from a JSON profile |
| `GET` | `/health` | Liveness probe |
| `GET` | `/version` | Build info and environment |

**Example request**
```bash
curl -X POST http://localhost:8000/recommend \
  -H 'Content-Type: application/json' \
  -d '{"skin_type":"dry","age":30,"concerns":["dehydration"],"climate":"cold","budget":"medium","routine_preference":"balanced","sensitivities":[]}'
```

**Profile fields**

| Field | Type | Values |
|-------|------|--------|
| `skin_type` | string | `oily`, `dry`, `combination`, `normal`, `sensitive` |
| `age` | int | 0–120 |
| `concerns` | list[string] | `acne`, `aging`, `hyperpigmentation`, `dehydration`, `redness`, `dullness`, `blackheads` |
| `climate` | string | `humid`, `dry`, `temperate`, `cold` |
| `budget` | string | `low`, `medium`, `high` |
| `routine_preference` | string | `minimal`, `balanced`, `comprehensive` |
| `sensitivities` | list[string] | optional e.g. `fragrance`, `retinoids`, `salicylic_acid` |

## Running tests

```bash
pytest --cov=src --cov-branch --cov-report=term-missing
```

## Docker

**Build**
```bash
docker build -t skincare-routine-classifier:latest .
```

**Run**
```bash
docker run -p 8000:8000 skincare-routine-classifier:latest
```

**Health check**
```bash
curl http://localhost:8000/health
```
