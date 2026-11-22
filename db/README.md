# Database

Alembic migrations for the synthetic claims schema live in `migrations/`. Apply them with:

```bash
python -m alembic -c db/alembic.ini upgrade head
```

`make seed` does that before loading rows. The `vector` extension is created here. Vector columns wait until Phase 3.
