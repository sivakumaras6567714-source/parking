# ParkFlow — Parking Facility Operations System

A self-contained college project built with **React + Flask + SQLite**. It uses manual entry/exit records only: no sensor hardware and no payment gateway.

## Features
- Role-based demo access: Parking Attendant, Facility Manager, Cashier, Administrator.
- Create parking zones and slots; view available/occupied spaces.
- Manually register vehicle entry and generate a ticket number.
- Process vehicle exits and calculate fees using configurable hourly rates, grace periods and daily maximums.
- Dashboard, daily revenue report and vehicle-type summary.
- Staff account creation (Administrator only).

## Requirements
- Python 3.9+
- Node.js 18+

## Run the backend
Open a terminal:
```bash
cd backend
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
python app.py
```
The API runs at `http://localhost:5000`. SQLite file `backend/parking.db` is created automatically.

## Run the frontend
Open a second terminal:
```bash
cd frontend
npm install
npm run dev
```
Open the local URL printed by Vite (usually `http://localhost:5173`).

## Demo logins
| Role | Username | Password |
|---|---|---|
| Administrator | admin | admin123 |
| Facility Manager | manager | manager123 |
| Parking Attendant | attendant | attendant123 |
| Cashier | cashier | cashier123 |

## Important notes
- This is a learning/demo project. Change demo passwords before any real deployment.
- The API uses a simple `X-User` header to demonstrate role permissions; production systems should use secure sessions/JWT, password hashing such as bcrypt/Argon2, HTTPS, CSRF protection, audit logging and stronger validation.
- Fee calculation rounds any started hour up to a full hour after the configured grace period. The daily maximum is applied per 24-hour period.
- No real payment is collected. The cashier records the exit and the calculated fee only.
