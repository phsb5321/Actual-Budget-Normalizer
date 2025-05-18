# Actual Budget Normalizer - Dockerized API

This project provides a FastAPI-based API for normalizing bank transactions using LLMs, with local bucket storage and SQLite for categories/payees. It is ready for local or cloud deployment with Docker Compose.

## Features

- FastAPI app with OpenAPI docs
- SQLite for job, category, and payee storage
- Local bucket storage (with optional S3 API via MinIO)
- Colorized logs, robust error handling
- Ready-to-use Dockerfile and docker-compose.yml

## Quickstart

1. **Build and start the stack:**

```zsh
docker compose up --build
```

2. **API available at:**

   - http://localhost:8000/docs (Swagger UI)
   - http://localhost:8000/redoc

3. **MinIO bucket (optional S3 API):**

   - http://localhost:9001 (console, user: minioadmin, pass: minioadmin)
   - http://localhost:9000 (S3 API)

4. **Persistent volumes:**
   - `jobs/`, `logs/`, `bucket/` are mounted for data persistence.

## Environment Variables

- `DATABASE_URL`: Path to SQLite DB (default `/app/jobs.db`)
- `CATEGORIES_FILE`: Path to categories JSON (default `/app/categories.json`)
- `PAYEES_FILE`: Path to payees JSON (default `/app/payees.json`)
- `BUCKET_PATH`: Path to bucket storage (default `/app/bucket`)

## Notes

- The API node will work out-of-the-box for local development and can be extended for cloud/S3 storage.
- MinIO is optional; you can use just the local `bucket/` directory if you don't need S3 API.
- All data is persisted in local volumes for easy backup and migration.

---

For more details, see the main README.md.
