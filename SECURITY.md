# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report security issues by emailing **parabvedang007@gmail.com** with:

- A description of the vulnerability
- Steps to reproduce
- Potential impact

You will receive a response within 48 hours. If the issue is confirmed, a patch will be released as soon as possible (typically within 7 days for critical issues).

## Scope

infra-graph runs entirely locally. It parses files on your filesystem and exposes a local MCP stdio server. It does not make outbound network requests except during the optional `--mode deep` pass, which uses your own API key to call an LLM of your choice.

Sensitive files (`.tfstate`, `.tfvars`, secrets) should be excluded via `.infraignore`. The tool does not log or transmit file contents.
