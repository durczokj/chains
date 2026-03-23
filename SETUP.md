# Setup

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/)

## Quick Start

```bash
git clone <repo-url> && cd chains-1
docker compose up --build -d
```

The app is now running at **http://localhost:8080**.

## Verify

```bash
curl http://localhost:8080/api/events/
```

You should get a `200` response with an empty results list.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/api/events/` | List or create events |
| GET/DELETE | `/api/events/{id}/` | Retrieve or delete an event |
| GET/POST | `/api/countries/` | List or create countries |
| GET/POST | `/api/code-types/` | List or create code types |
| POST | `/api/product-families/recompute/` | Recompute all product families |
| GET | `/api/product-families/` | List product families |
| GET | `/api/resolve/?code={code}` | Resolve a code to its product family |
| GET | `/api/resolve/reverse/?family={identifier}` | Get all codes in a family |

There is also a web UI at http://localhost:8080.

## Stop / Reset

```bash
# Stop (keeps data)
docker compose down

# Stop and wipe the database
docker compose down -v
```
