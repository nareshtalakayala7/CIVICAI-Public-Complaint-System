# CIVICAI — AI-Powered Public Complaint Management System

CIVICAI is a runnable B.Tech Community Service Project demonstration. It connects a citizen reporting portal, administrator command center and department officer workspace. The interface is a responsive dark smart-city dashboard built with Bootstrap 5.3 and custom CSS; Chart.js supplies dashboard graphs and Bootstrap Icons supply the interface icons. The application includes server-side authentication, role checks, a PostgreSQL-ready relational model, private image uploads, complaint history, explainable NLP-style triage, analytics, a JSON API and optional SMTP email.

![CIVICAI public home screen](docs/screenshots/01-home.png)

## Quick start (Windows PowerShell)

Python 3.10+ is recommended. From this folder:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). On first start the app creates a local SQLite database at `instance/civicai.db` and seeds demonstration accounts and sample complaints. The sample passwords are for local classroom demonstration only.

## Demo logins

| Module | Email | Password |
|---|---|---|
| Citizen | `citizen@civicai.demo` | `CivicAI@2026` |
| Admin | `admin@civicai.demo` | `CivicAI@2026` |
| Department officer | `officer@civicai.demo` | `CivicAI@2026` |

Citizen login: `/login` · Admin login: `/admin/login` · Officer login: `/officer/login`.

## PostgreSQL

The default is SQLite for a zero-setup demonstration. To use PostgreSQL, create a database, copy `.env.example` to `.env`, and set:

```dotenv
DATABASE_URL=postgresql+psycopg://civicai:your-password@localhost:5432/civicai
```

The app creates tables on startup. `schema.sql` is the standalone PostgreSQL DDL reference and can also be applied with `psql`. For a containerized demo, `docker compose up --build` starts PostgreSQL and Flask on port 5000. Change the example secrets and database password before using that setup outside a local demo.

## Main flows

1. Register or sign in as a citizen, submit a report, and receive a tracking ID such as `CVC-261110-ABC123`.
2. The report form can attach up to three verified JPG, PNG or WebP images (5 MB maximum total request), and optionally browser coordinates. Uploaded images are stored outside Flask's public static folder and served through an access-checked route.
3. The local triage module suggests a category, responsible department, priority, short summary and confidence. The `Get an AI triage preview` button calls `/api/triage`; the server reruns triage at submission. Similar descriptions are flagged for staff review.
4. Admins review the queue, select a department/officer, and update status. Officers see only their assigned reports and add a resident-facing progress note or resolution.
5. Citizens can follow the history from their dashboard or public tracking page. Public tracking requires both the tracking ID and the registered email or phone. On resolution, the citizen can rate the outcome.
6. Admin analytics show monthly volume, department distribution, priority demand, resolution rate and average completion time. The print control uses the browser's print dialog.

## REST API

All API responses are JSON. Obtain an 8-hour JWT:

```http
POST /api/auth/token
Content-Type: application/json

{"email":"citizen@civicai.demo","password":"CivicAI@2026"}
```

Use `Authorization: Bearer <access_token>`:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/stats` | Aggregate public counters |
| `POST` | `/api/triage` | AI triage preview; JSON `title`, `description` |
| `GET` | `/api/complaints` | Recent complaints within the caller's citizen/officer scope; admins see all |
| `POST` | `/api/complaints` | Citizen creates a complaint using JSON `title`, `description`, `location` |

## Configuration

Copy `.env.example` to `.env`; `python-dotenv` loads local variables when installed. Set independent random `SECRET_KEY` and `JWT_SECRET_KEY` values for any shared deployment. Set `SESSION_COOKIE_SECURE=1` behind HTTPS. Demo seeding can be disabled with `CIVICAI_SEED_DEMO=0` after the classroom database is prepared.

Optional outbound email uses `SMTP_HOST`, `SMTP_PORT`, `SMTP_STARTTLS`, `SMTP_USERNAME`, `SMTP_PASSWORD` and `SMTP_FROM`. In-app notification rows are always written; SMTP is not needed to run the demo. Contact form messages are stored as contact-channel notification records.

## Project structure

```text
CIVICAI/
├── app.py                    Flask routes, SQLAlchemy models, auth, API and seed data
├── civicai/triage.py          Explainable English/Telugu keyword NLP and duplicate matching
├── schema.sql                 PostgreSQL schema
├── templates/                 Responsive Jinja pages and shared timeline
├── static/css/style.css       Dark smart-city UI system and mobile layouts
├── static/js/                 Navigation, charts, triage preview and report form helpers
├── instance/uploads/          Private verified image storage (created at runtime)
├── docs/PROJECT_REPORT.md     Full CSP report, diagrams and test plan
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

## Manual demonstration / verification checklist

- Register a citizen; edit their address and language in Profile.
- Submit a report with a location, photo and detailed description; verify the generated ID, AI preview, dashboard card and status history.
- Try public tracking with the correct ID and registered email/phone, then with a wrong contact value.
- Sign in as admin. Search/filter the complaint queue, change status, department and officer, and inspect citizens, departments and analytics.
- Sign in as the demo officer. Open the road assignment, add a progress note, and mark it resolved.
- Return as the citizen and submit 1–5 star feedback.
- Request a JWT and call the API endpoints above.

The companion report includes the architecture, data model, DFD, ER and UML diagrams, implementation notes, results, limitations, future work and this acceptance checklist.

## Scope and production notes

The classifier is an offline, explainable weighted-keyword baseline, not a trained model or official dispatch decision. It supports English and common Telugu civic terms. Similarity is Jaccard token overlap. Staff must verify triage and duplicates. Email is optional and no external geocoder or map provider is connected. Add rate limiting, account recovery, CAPTCHA/abuse controls, audit review, retention policies, malware scanning, migrations, backups, monitored SMTP and a trained/evaluated multilingual model before public production deployment.
