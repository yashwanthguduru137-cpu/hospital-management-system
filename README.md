# CarePoint — Hospital Management System

A runnable BTech full-stack demo showing hospital workflows and database concepts.

## Technology
- Frontend: HTML5, CSS3, vanilla JavaScript (responsive dashboard)
- Backend: Python Flask REST API
- Relational database: SQLite with primary/foreign keys and joins
- NoSQL concept: JSON document collection stored in SQLite
- Graph concept: relationship-edge table for patient ↔ doctor care links
- Cache: in-memory dashboard cache with 20-second TTL
- Transactions: atomic appointment booking and bed allocation
- Security: password hashing, session authentication, parameterized SQL

> This is an educational demo with synthetic data, not a production medical-record system. Do not enter real patient information.

## Run locally (Windows)
1. Install Python 3.10 or newer.
2. Extract the ZIP and open a terminal in this folder.
3. Create and activate a virtual environment:
   ```powershell
   py -m venv .venv
   .venv\Scripts\activate
   ```
4. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
5. Start the server:
   ```powershell
   python app.py
   ```
6. Open http://127.0.0.1:5000

## Demo login
- Username: `admin`
- Password: `admin123`

## Included modules
- Overview dashboard and bed capacity
- Patient create/search/delete
- Doctor create/list
- Appointment booking, conflict validation and status updates
- Admission and bed allocation with duplicate-bed protection
- Database architecture explainer and API endpoints

## API quick test
- `GET /health` — backend health
- `POST /api/login` — JSON `{ "username":"admin", "password":"admin123" }`
- `GET /api/dashboard`
- `GET|POST /api/patients`
- `GET|POST /api/doctors`
- `GET|POST /api/appointments`
- `PATCH /api/appointments/<id>`
- `GET|POST /api/admissions`

All `/api/*` routes other than login require an authenticated session.

## Notes on database concepts
SQLite is used so the complete project runs locally without separate database services. The JSON document table and relationship-edge table demonstrate NoSQL-style and graph-style data models in a lightweight way. For a production extension, replace these with MongoDB and Neo4j, and move SQLite to PostgreSQL/MySQL or a managed cloud database. Set `SECRET_KEY` and `HOSPITAL_DB` environment variables before deployment.


## Online patient appointment booking

Patients can open the public booking page at `http://127.0.0.1:5000/book` without an admin login. They can enter their contact details, choose an available doctor, and request an appointment. New online requests are saved with `Pending` status and appear in the admin dashboard under Appointments. The admin can change the status to Scheduled, Completed, or Cancelled. The login page also contains a link to the patient booking portal.

For a real hospital deployment, add HTTPS, stronger secret-key configuration, rate limiting, consent/privacy notices, and appropriate health-data security controls before collecting real patient information.
