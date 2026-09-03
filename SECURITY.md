# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.4.x   | Yes       |
| < 0.4.0 | No        |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report security issues by email to **scrimreaperdev@proton.me**. Include:

- A description of the vulnerability
- Steps to reproduce it
- The potential impact

You will get a response within 48 hours. If we confirm the issue, we release a patch as soon as possible — typically within 7 days for critical issues.

## Scope

iaclens runs entirely on your machine. It parses files on your filesystem and exposes a local MCP stdio server. It makes no outbound network requests.

Exclude sensitive files (`.tfstate`, `.tfvars`, secrets) with `.infraignore`. iaclens does not log or transmit file contents.
