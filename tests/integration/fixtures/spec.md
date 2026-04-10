# Spec: Add User Authentication

## Goal
Add email/password authentication with JWT tokens to the API.

## Decisions
- Use bcrypt for password hashing
- JWT tokens with 1h expiry
- No refresh tokens in v1

## Invariants
- Passwords are never stored in plaintext
- All auth endpoints return consistent error format
- JWT secret is loaded from environment variable

## Acceptance Criteria
- Users can register with email + password
- Users can login and receive a JWT
- Protected routes reject unauthenticated requests

## Security Boundaries
- Rate limiting on login endpoint (not in scope for v1)
- JWT secret rotation (not in scope for v1)
