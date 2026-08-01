# Security

## Reporting a vulnerability

Email support@rapidoddsapi.com. Please do not open a public issue.

Include what you found, how to reproduce it, and what an attacker could do with
it. We will confirm receipt within a few business days.

## Supported versions

Fixes go to the latest release.

## Keeping your API key safe

Your key is passed as a query parameter, so it appears in URLs.

- Keep it server side. Never put it in browser JavaScript, a mobile app, or any
  other client a user can read.
- Load it from an environment variable or secret store, not a committed file.
- Regenerate it from your dashboard if it is ever exposed.
