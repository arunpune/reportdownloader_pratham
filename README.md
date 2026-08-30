# Suprajit Portal

A FastAPI + Bootstrap report portal. It automatically indexes `.xlsx` files found below one configured folder. It does **not** copy or move reports; it only stores metadata and streams the original file after authorization.

## Run locally (Windows)

1. Open PowerShell in this folder.
2. Create your local settings file:

   ```powershell
   Copy-Item .env.example .env
   ```

3. Edit `.env` and set `REPORTS_ROOT` to your own result folder. For the supplied sample use `D:\pass`.
4. Install and run:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   uvicorn app.main:app --reload
   ```

5. Open http://127.0.0.1:8000.

Use the admin email and password from `.env` (initial default: `admin@local` / `ChangeMe123!`). Change them before any real use.

## Automatic file updates

At startup, the application scans every date folder under `REPORTS_ROOT`. It then uses a Watchdog file watcher plus a periodic rescan (default every 30 seconds). Put a new `.xlsx` into a date folder and it appears automatically—no manual database upload is needed.

File names are expected in this form:

```text
I-QUBE-MLX90421_13-06-2026_22.16.55_8.xlsx
```

The scanner extracts recipe, report date, time, serial number, filename, file path, size, and status. Files from today are indexed as `Generating` and cannot be downloaded. Any earlier report is `Completed` and can be downloaded by an approved user.

## Admin access is locked to your machine

There is only ever one admin account (seeded from `ADMIN_EMAIL` /
`ADMIN_PASSWORD`), but knowing that email/password is **not enough** to
reach the admin console from somewhere else. On every request, the backend
checks the caller's IP against `ADMIN_ALLOWED_HOSTS` in `.env`:

- If the request comes from an allowed IP (default `127.0.0.1,::1`, i.e.
  your own laptop), the admin account gets the full Admin console
  (approve/reject/disable users, view logs).
- If the *same* admin account logs in from anywhere else - another state,
  another laptop, a colleague who guessed the password - the login still
  succeeds, but they land on the normal user dashboard only. There is no
  "Admin console" link and `/admin` silently redirects to the dashboard;
  the admin actions on the backend also refuse the request.

If you later move the web server itself off your laptop (e.g. onto a cloud
VPS reachable over a VPN, per the architecture above), add the IP you
connect to the VPN with to `ADMIN_ALLOWED_HOSTS` so you can still reach the
admin console while everyone else remains a plain user. Regular users never
need to be added here - this setting only affects who is allowed to *use*
the ADMIN role, not who can log in.

## Production notes

- Change `DATABASE_URL` to PostgreSQL, e.g. `postgresql+psycopg://user:password@host:5432/qube_reports`, and install `psycopg[binary]`.
- Keep `REPORTS_ROOT` on a private server/VPN path; never expose SMB or the folder itself to the internet.
- Run FastAPI behind HTTPS and a reverse proxy. The sample session cookie configuration is for local development.
