# Invoice Graph Web App 📊

A FastAPI-based web application that automatically processes bill invoices from Gmail attachments, extracts payment data, and generates visual payment graphs. Users authenticate with Google OAuth, and the app securely stores tokens and session data in PostgreSQL.

🌐 **Live Demo:** [https://invoice-graph.org](https://invoice-graph.org)

---

## Features ✨

- **🔐 Google OAuth Authentication**: Secure login with Google accounts
- **📧 Gmail Integration**: Automatically searches and retrieves email attachments
- **📄 Bill Processing**: Extracts payment information from PDF/image attachments
- **📈 Data Visualization**: Generates interactive payment graphs
- **💾 Secure Storage**: Encrypted token storage in PostgreSQL
- **📥 Export Options**: Download graphs as PNG or PDF
- **🔒 Session Management**: Secure session handling with encrypted cookies
- **🐳 Docker Ready**: Containerized deployment with Docker Compose

---

## Tech Stack 🛠️

### Backend
- **FastAPI** - Python web framework
- **PostgreSQL** - Production database

### Authentication & Security
- **Google OAuth 2.0** - User authentication
- **Cryptography** - Token encryption
- **Starlette SessionMiddleware** - Session management

### Infrastructure
- **Docker & Docker Compose** - Containerization
- **Nginx** - Reverse proxy (production)
- **Let's Encrypt** - SSL/TLS certificates

---
# Database Schema 🗄️

## Overview

The application uses **PostgreSQL** with two main tables: `users` and `sessions`. The database stores user information, encrypted OAuth tokens, and manages session authentication.

## Tables

### 👤 `users` Table

Stores Google user information and their encrypted OAuth tokens.

```
┌─────────────────────────────────────────────────────────┐
│                       users                             │
├─────────────────────────────────────────────────────────┤
│ 🔑 g_id                VARCHAR(255)    PRIMARY KEY      │
│    email               VARCHAR(255)    UNIQUE           │
│    token               BYTEA           🔒 ENCRYPTED     │
│    created_at          TIMESTAMP                        │
│    expires_at          TIMESTAMP                        │
│    is_active           BOOLEAN                          │
│    last_accessed       TIMESTAMP                        │
└─────────────────────────────────────────────────────────┘
```


 `g_id` is Google user ID (unique identifier from Google OAuth)

 `token` is Encrypted Google OAuth token (encrypted with Fernet before storage)  
- Even if database is compromised, tokens remain protected

### 🔐 `sessions` Table

Manages active user sessions with automatic expiration.

```
┌─────────────────────────────────────────────────────────┐
│                     sessions                            │
├─────────────────────────────────────────────────────────┤
│ 🔑 session_id          VARCHAR(255)    PRIMARY KEY      │
│ 🔗 g_id                VARCHAR(255)    FOREIGN KEY      │
│    created_at          TIMESTAMP                        │
│    expires_at          TIMESTAMP                        │
│    is_active           BOOLEAN                          │
└─────────────────────────────────────────────────────────┘
```

`session_id` Unique session identifier (UUID generated on login)
`g_id`Links to the user (Foreign Key → `users.g_id`)


**Session Lifecycle:**
1. User logs in → new session created with random UUID
2. Session stored in encrypted cookie in user's browser
3. On each request, server validates session exists and hasn't expired
4. After 24 hours (or logout), session marked inactive


### Relationship

```
      users                    sessions
┌─────────────┐            ┌──────────────┐
│   g_id      │────────────│   g_id       │
│   email     │   1 : N    │   session_id │
│   token 🔒  │            │   expires_at │
└─────────────┘            └──────────────┘
```

**One-to-Many (1:N):**
- One user can have **multiple active sessions**
- Example: User logged in on phone + laptop = 2 sessions
- Each session links back to one user via `g_id`


### 🧹 Automatic Cleanup
- Expired sessions removed on application startup
- Expired tokens removed on application startup
- Query: `DELETE FROM sessions WHERE expires_at < NOW()`


## Project Structure 📁

```
Invoice-Graph-Web-App/
├── main.py                # FastAPI application entry point
├── storage.py             # Database operations (sessions, tokens)
├── model.py               # SQLAlchemy models
├── db.py                  # Database configuration
├── gmail_auth.py          # Google OAuth authentication
├── gmail.py               # Gmail API integration
├── bill.py                # invoice parser
├── graph_plot.py          # Graph generation
├── crypto.py              # Encryption utilities
├── templates/             # Jinja2 HTML templates
│    ├── graph.html
│    └── index.html
├── requirements.txt       # Python dependencies
├── Dockerfile             # Docker image definition
├── docker-compose.yml     # Docker services configuration
├── .env.example           # Environment template
├── .env                   # Local config (NOT committed)
├── .gitignore
└── README.md
```

---

## Usage 📖

1. **Visit the website:** Navigate to your deployed URL
2. **Login with Google:** Click "Login" and authenticate
3. **Enter search criteria:**
   - Email address to search
   - Subject filter (optional)
   - Keyword filter (optional)
   - Currency type
   - Date range
4. **Process bills:** The app will:
   - Search Gmail for matching emails
   - Download attachments
   - Extract payment data
   - Generate a visual graph
5. **Download graph:** Export as PNG or PDF
   - Example of graph.png output-
![Example graph output](graph.png)
---

## License 📄

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

