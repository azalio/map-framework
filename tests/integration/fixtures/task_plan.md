<MAP_Plan_v1_0>

## Goal
Add email/password authentication with JWT tokens to the API.

## Current Phase
EXECUTING

## Subtasks

### ST-001: Create User model with email/password fields
- **Status:** pending
- **AAG:** UserModel -> define(email, password) -> User record with hashed password
- **Files:** models/user.py
- **Complexity:** low | **Risk:** low

### ST-002: Add register endpoint
- **Status:** pending
- **AAG:** AuthRouter -> register(email, password) -> 201 with user_id | 409 duplicate
- **Files:** routes/auth.py, schemas/auth.py
- **Depends on:** ST-001
- **Complexity:** medium | **Risk:** medium

### ST-003: Add login endpoint with JWT
- **Status:** pending
- **AAG:** AuthRouter -> login(email, password) -> JWT token | 401 unauthorized
- **Files:** routes/auth.py, utils/jwt.py
- **Depends on:** ST-001
- **Complexity:** medium | **Risk:** high

### ST-004: Add auth middleware for protected routes
- **Status:** pending
- **AAG:** AuthMiddleware -> validate(token) -> request.user | 401
- **Files:** middleware/auth.py
- **Depends on:** ST-002, ST-003
- **Complexity:** medium | **Risk:** high

## Risks
- JWT secret management needs careful handling
- Password hashing performance under load

</MAP_Plan_v1_0>
