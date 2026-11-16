# API Keys & Secrets: what you need and where it goes

Rule: secrets live ONLY in (1) your local `.env` file, (2) Render environment variables, (3) GitHub Actions secrets.
The frontend gets exactly ONE setting: `VITE_API_BASE_URL`. Never put a key in frontend code.

| # | Name | Where to get it | Put it in |
|---|------|-----------------|-----------|
| 1 | `OPENAQ_API_KEY` | https://explore.openaq.org/register (free). Copy the key from your account page. | local `.env`, Render env, GitHub secret |
| 2 | `TOMTOM_API_KEY` | https://developer.tomtom.com/ → sign up → Dashboard → Keys. Enable Traffic API. No credit card. | local `.env`, Render env, GitHub secret |
| 3 | `DATABASE_URL` | Supabase → your project → Connect → **Session pooler** connection string (use the pooler, not "Direct"). Replace `[YOUR-PASSWORD]`. | local `.env`, Render env, GitHub secret |
| 4 | `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` | Supabase → Project Settings → API | local `.env` (optional; only for Storage). Service-role key is private: backend only. |
| 5 | `JWT_SECRET` | You generate it: `python -c "import secrets;print(secrets.token_urlsafe(48))"` | local `.env`, Render env |
| 6 | `CRON_SECRET` | You generate it the same way | local `.env`, Render env, GitHub secret |
| 7 | `ADMIN_EMAIL`, `ADMIN_PASSWORD` | You choose. Used once by `scripts/seed.py` to create the first admin. | local `.env` only |
| - | Open-Meteo | No key needed | - |

Local development works with NO keys (SQLite database, no live data). Add keys as each module is built.
