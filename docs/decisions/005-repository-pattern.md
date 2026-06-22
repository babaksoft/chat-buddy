Decision:
Use a repository layer between application services and SQLAlchemy.

Rationale:
Decouple business logic from persistence implementation.

Alternatives:
Direct SQLAlchemy usage in services.

Trade-offs:
Additional abstraction layer but improved maintainability and testability.
