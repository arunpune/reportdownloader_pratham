 <div align="center">

# 📊 Suprajit Portal

### Secure Excel Report Management Platform

A FastAPI and Bootstrap-based web application that automatically indexes Excel reports, tracks report status, and provides controlled access to authorized users.

<p>
  <img src="https://img.shields.io/badge/Python-Backend-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-Framework-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Bootstrap-Frontend-7952B3?style=for-the-badge&logo=bootstrap&logoColor=white" alt="Bootstrap" />
  <img src="https://img.shields.io/badge/Excel-Report_Processing-217346?style=for-the-badge&logo=microsoftexcel&logoColor=white" alt="Excel" />
</p>

**Automated Indexing · Report Tracking · Access Control · Secure Downloads**

</div>

---

## 📌 Overview

Suprajit Portal simplifies the discovery and controlled access of Excel reports stored in a configured directory.

The application automatically indexes `.xlsx` files, stores report metadata, tracks report status, and allows authorized users to download eligible reports through a centralized web interface.

**Original files remain in their existing locations.** The portal does not copy or move reports; it stores metadata and streams the original file after authorization.

## ✨ Key Features

| Feature                    | Description                                                                            |
| -------------------------- | -------------------------------------------------------------------------------------- |
| 🔄 Automatic Indexing      | Discovers Excel reports within supported date-based folders.                           |
| 👁️ File System Monitoring | Uses Watchdog and periodic rescans to detect file-system changes.                      |
| 📑 Metadata Extraction     | Extracts recipe, report date, time, serial number, filename, file path, and file size. |
| 📊 Report Status Tracking  | Distinguishes reports that are generating from completed reports.                      |
| 🔐 Authorized Downloads    | Restricts protected report downloads to approved users.                                |
| 🛡️ Admin IP Restrictions  | Limits administrative privileges using `ADMIN_ALLOWED_HOSTS`.                          |
| 👥 User Management         | Supports approving, rejecting, and disabling users.                                    |
| 🧾 Administrative Logs     | Provides access to application logs through the admin console.                         |
| 📥 Original File Streaming | Streams the original Excel file without copying it into the application.               |

## 🧰 Technology Stack

* **Backend:** Python, FastAPI
* **Frontend:** Bootstrap
* **Report Format:** Microsoft Excel (`.xlsx`)
* **File Monitoring:** Watchdog
* **Database:** Configurable through `DATABASE_URL`
* **Application Server:** Uvicorn

## 🏗️ System Architecture

```text
┌──────────────────────────────┐
│       User / Admin           │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│    FastAPI Web Application   │
│ Authentication & Permissions │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│       Web Dashboard          │
│ Reports • Status • Access    │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│     Report Indexing          │
│ Startup Scan + Watchdog      │
│       + Periodic Rescan      │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│   Configured Report Folder   │
│       Original .xlsx Files   │
└──────────────────────────────┘
```

## ⚙️ Getting Started

### Prerequisites

* Windows operating system
* Python installed and available through the `py` command
* Git installed
* Access to the folder containing the Excel reports

### 1. Clone the Repository

```powershell
git clone https://github.com/arunpune/reportdownloader_pratham.git
cd reportdownloader_pratham
```

### 2. Configure Environment Variables

Create your local environment file:

```powershell
Copy-Item .env.example .env
```

Open `.env` and set `REPORTS_ROOT` to the directory containing your reports.

For the supplied sample configuration:

```env
REPORTS_ROOT=D:\pass
```

Review the other environment variables, especially the administrator credentials, database URL, and allowed admin hosts.

### 3. Create a Virtual Environment

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 4. Install Dependencies

```powershell
python -m pip install -r requirements.txt
```

### 5. Start the Application

```powershell
uvicorn app.main:app --reload
```

Open the application in your browser:

**http://127.0.0.1:8000**

> ⚠️ **Security warning:** The initial sample credentials are `admin@local` / `ChangeMe123!`. Change them before real use. Never use default credentials in a shared or production environment.

## 📂 Automatic Report Discovery

At startup, the application scans supported date folders under `REPORTS_ROOT`. It then uses Watchdog to monitor file-system changes and performs a periodic rescan every **30 seconds by default**.

Place a new `.xlsx` file in a supported date folder, and it can be indexed automatically without a manual database upload.

### Expected File Naming Convention

```text
I-QUBE-MLX90421_13-06-2026_22.16.55_8.xlsx
```

The scanner extracts supported metadata, including:

* Recipe or report identifier
* Report date and time
* Serial number
* Filename and file path
* File size
* Report status

### Report Status Logic

| Status          | Condition                         | Download Availability       |
| --------------- | --------------------------------- | --------------------------- |
| 🟡 `Generating` | Report date is today              | Downloads disabled          |
| 🟢 `Completed`  | Report date is earlier than today | Available to approved users |

Reports dated today are indexed as `Generating` and cannot be downloaded. Reports from earlier dates are marked `Completed` and can be downloaded by approved users, subject to authorization checks.

## 🔐 Authentication & Admin Access Control

The application separates regular user access from administrative privileges.

### Admin Account

The application seeds a single admin account using `ADMIN_EMAIL` and `ADMIN_PASSWORD`.

Knowing the admin email and password alone is not sufficient to access the admin console. The backend checks the caller's IP against `ADMIN_ALLOWED_HOSTS` on every request.

Default local-development configuration:

```env
ADMIN_ALLOWED_HOSTS=127.0.0.1,::1
```

### Access Rules

* **Allowed IP:** The admin account can access the admin console, including supported user-management actions and log viewing.
* **Non-allowed IP:** The same account may sign in but receives the normal user dashboard instead of administrative privileges.
* **Admin route protection:** Access to `/admin` redirects to the regular dashboard for a non-allowed IP, and backend administrative actions reject unauthorized requests.
* **Regular users:** Do not need to be added to `ADMIN_ALLOWED_HOSTS`. This setting controls who can exercise the ADMIN role, not who can log in.

### Remote Server and VPN Access

If the web server is moved from a local machine to a remote server or cloud VPS reachable through a VPN, configure `ADMIN_ALLOWED_HOSTS` for the trusted client IP address or addresses used to access the admin console.

This allows authorized administrators to retain administrative access while other users remain restricted to regular functionality.

When deploying behind a reverse proxy, verify how the application determines the client's IP address. Trust forwarded IP headers only from correctly configured, trusted proxies; otherwise, clients may be able to spoof their apparent IP address.

## 🗄️ Database Configuration

The application database is configured through `DATABASE_URL`.

For a PostgreSQL setup, use a connection string similar to:

```env
DATABASE_URL=postgresql+psycopg://user:password@host:5432/qube_reports
```

Install the PostgreSQL driver if it is not already included in the project's dependencies:

```powershell
python -m pip install "psycopg[binary]"
```

Replace the example connection details with the appropriate values for your environment.

**Important:** Do not commit database passwords, application secrets, or other sensitive environment variables to GitHub.

## 🔒 Production & Security Notes

For a deployment outside local development, consider the following requirements:

* **Credentials:** Replace default administrator credentials with strong, unique passwords.
* **Database:** Configure PostgreSQL if required by the deployment environment.
* **Report storage:** Keep `REPORTS_ROOT` on private server storage or a trusted VPN-accessible path.
* **File sharing:** Never expose an SMB share or the report directory directly to the public internet.
* **HTTPS:** Run FastAPI behind HTTPS using a properly configured reverse proxy.
* **Session security:** Review session-cookie settings and application secrets. The sample cookie configuration is intended for local development.
* **Admin restrictions:** Verify `ADMIN_ALLOWED_HOSTS` and trusted proxy IP handling for the actual network architecture.
* **Authorization:** Test user approval, admin access restrictions, and report-download permissions.

These measures help protect report confidentiality and reduce the risk of unauthorized access.

---

<div align="center">

**Suprajit Portal**

*Automated report discovery. Controlled access. Streamlined workflows.*

</div>
