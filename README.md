# GeM Bid Automation

Django is the main application. Django REST Framework exposes the API, Django Templates provide the initial interface, and Celery/Redis run bid processing outside HTTP requests. The code is modular so future extraction or a separate FastAPI processing service can be added without replacing Django's business workflows.

## Current implementation

- Authenticated Django Admin and web login.
- Private PDF upload (50 MB limit), upload validation, per-user bid listing and APIs.
- Celery tasks for PDF text/metadata extraction, hyperlink discovery, and Phase 2 linked-file processing.
- Retried HTTP downloads with redirect and public-address checks, bounded file size, and a Playwright fallback for browser-only links.
- Recursive PDF link processing (up to four levels and 100 linked files per bid), a document graph, processing status, and private owner-only file viewing.
- Bid, linked-document, company profile/repository and processing-job records.
- Reusable company profile and supporting-document repository, with per-bid PDF draft generation for BoQ compliance, specification review, experience criteria, MSME requests, and an OEM turnover evidence index.
- DRF filtering/search/pagination and OpenAPI schema and Swagger UI routes.
- Docker Compose services for Django/Gunicorn, Celery, PostgreSQL, Redis and Nginx.

The app keeps reusable company details, certificates, signature, and stamp in the existing company profile. Bid-specific data and edits are removed when a bid is completed, deleted, or expires. PDF text extraction and conservative local requirement matching run in Python. Detected requirements are marked low-confidence for verification, and the full template list remains available when no supported requirement is matched. Scanned-PDF OCR and automated bid validation are not provided.

## Local setup

Use Python 3.12+. From this directory:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

If you do not activate the environment, run management commands with the project interpreter, for example `.venv/bin/python manage.py runserver`. Running `python manage.py ...` with a system Python that does not have Django installed will produce `ModuleNotFoundError: No module named 'django'`.

Redis and a Celery worker must both be running before you upload a bid. For a local setup, use three terminals (skip the Redis start if it is already running):

```sh
# Terminal 1
redis-server --port 6379

# Terminal 2
.venv/bin/celery -A config worker --loglevel=info

# Terminal 3
.venv/bin/python manage.py runserver

# Terminal 4
.venv/bin/celery -A config beat --loglevel=info
```

With SQLite, the worker defaults to one concurrent task and the database waits up to 30 seconds for a write lock. Lock errors in bid extraction and linked-document processing are retried automatically. Set `CELERY_WORKER_CONCURRENCY` to override worker concurrency if needed.

Run Celery Beat alongside the worker to delete expired bid workspaces daily. The default expiry is 30 days and can be changed in `/admin/` under **Bid system settings**. You can also run `.venv/bin/python manage.py cleanup_expired_bids` manually or from a scheduler.

Storage maintenance is available through `.venv/bin/python manage.py deduplicate_storage` (dry run) and `.venv/bin/python manage.py cleanup_generated_files` (dry run). Both commands require `--apply --backup-dir /path/outside/storage` before changing files; duplicate and legacy generated files are copied there before removal. Generated PDFs are rendered from editable document data when requested. Identical linked downloads reuse an existing file, and re-uploading an unchanged company signature or stamp does not create another copy.

The local default is `redis://localhost:6379/0`. Docker Compose overrides this with its internal `redis` service hostname.

If Chromium or Google Chrome is not already installed, install a Playwright browser in the local virtual environment to enable browser fallback:

```sh
playwright install chromium
```

Opening a bid's **View** page lists discovered links and downloaded files. Pending links are queued automatically after PDF extraction; use **Download / retry pending links** to start or retry them manually. The table refreshes while downloads are in progress.

Open `/` for bids, `/admin/` for administration, `/api/bids/` for the authenticated REST API, and `/api/docs/` for Swagger UI. `/api/schema/` serves the OpenAPI document. SQLite is the local default; set `DATABASE_URL` for PostgreSQL.

## Docker Compose

Copy `.env.example` to `.env`, replace `DJANGO_SECRET_KEY`, then run `docker compose up --build`. The app is served on port 8080 through Nginx. Set `DJANGO_DEBUG=0`, a production secret and production `DJANGO_ALLOWED_HOSTS` before deployment; TLS termination and secure-cookie settings should be configured at the production edge.

Uploads are stored in `storage/`, outside public static paths. Nginx denies `/media/`; bid and downloaded files are served through authenticated, owner-checked application endpoints.
# Company profile and bid document generation

Sign in, open **Company profile**, and enter reusable company, MSME, OEM, and authorized-signatory information. Upload an authorized PNG/JPEG signature in **Reusable signature**; generated PDFs embed it, and replacing or removing it refreshes existing generated PDFs. Supporting certificates and financial evidence can be uploaded there and remain private to that account.

The dashboard displays active bids versus the effective limit. The default is one; staff can configure a per-user override under **Bid retention policies** and change the site default under **Bid system settings**. A bid can be completed or deleted from the dashboard, which removes bid-specific rows and files while preserving the company profile and reusable documents.

For each uploaded bid, choose **Prepare PDFs**. Verify the bid, buyer, invoice GSTIN/address, and BoQ lines. The page shows locally detected requirements and missing common certificates, and always offers the complete template list for manual review. Use **Create a custom PDF template** for a bid-specific document not covered by the built-in templates; enter its title and text, then edit it in the text editor and use the live PDF preview or download the generated draft. Each document remains separate. PDFs are rendered on demand rather than retained as files.

- Experience Criteria
- Past Performance
- Bidder Turnover
- Additional Doc 1 (BoQ compliance)
- Additional Doc 2 (company evidence index)
- Certificate requested in ATC (evidence index; the buyer's exact certificate wording must be checked)
- Compliance of BoQ specifications and supporting document
- OEM annual-turnover evidence index

Generated PDFs are drafts with an unsigned signature area. Verify every bid-specific value and statement before signing or submitting. The OEM turnover cover is only an index; upload original ITR, audited statements, or certificates as supporting files separately. No source evidence is fabricated or embedded, and generated PDFs are never combined or persisted as files.
