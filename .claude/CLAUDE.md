# Project Context

This file provides context for Claude Code sessions.

# Base Instructions

These instructions apply to all projects.

## Code Quality

- Write clean, readable, self-documenting code
- Prefer composition over inheritance
- Keep functions small and focused (single responsibility)
- Use meaningful variable and function names
- Avoid premature optimization

## Git Workflow

- Write clear, concise commit messages
- Use conventional commits format: `type(scope): description`
- Keep commits atomic and focused
- Always pull before pushing
- Use feature branches for new work

## Security

- Never commit secrets, API keys, or credentials
- Use environment variables for configuration
- Validate all user input
- Follow OWASP guidelines for web applications
- Review dependencies for known vulnerabilities

## Testing

- Write tests before or alongside code (TDD/eval-driven)
- Aim for meaningful coverage, not 100% coverage
- Test edge cases and error conditions
- Keep tests fast and independent

## Documentation

- Document the "why", not just the "what"
- Keep READMEs up to date
- Use inline comments sparingly, only for complex logic
- Maintain architectural decision records for significant choices

## Communication

- Ask clarifying questions before making assumptions
- Explain your reasoning when proposing changes
- Flag potential issues early
- Be concise but thorough

