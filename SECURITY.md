# Security Policy

## Supported versions

Forgeway is an early public technical preview. Only the current `0.1.x`
line is supported — there is no older release branch receiving fixes.

## What Forgeway actually is, security-wise

This is a fixture-driven demo and CLI, not a production service. Concretely:

- **No network callouts.** The decision engine (`app/engine/`,
  `app/core/engine/`) is pure computation over local fixtures and locally
  saved benchmark results — it never calls out to a cloud API, a license
  server, or any third-party endpoint.
- **No authentication, anywhere.** The API (`api/app/main.py`) has no
  login, no API keys, no sessions — every route is open. This is
  appropriate for a local demo; it is not something to expose beyond
  `localhost`/your own LAN.
- **No server-side persistence.** `api/app/state.py` is a plain in-memory
  dict — every recommendation is gone on restart. There is no database to
  secure or leak.
- **No cloud credentials anywhere in this repo.** Nothing here holds an
  AWS/GCP/Azure key, a Hugging Face token, or any other secret — a real
  `forgeway bench` run needs an `HF_TOKEN` in your own environment for
  gated models, but Forgeway itself never stores or transmits it.

Given that, most of what a typical `SECURITY.md` covers (production
hardening, data breach handling, dependency-confusion mitigations for a
deployed service) doesn't apply here. The one real surface worth naming:

**CORS is intentionally permissive for local/LAN testing, and that is not
a production posture.** `api/app/main.py`'s `CORSMiddleware` uses an
`allow_origin_regex` that accepts any `http://localhost:<port>` or
`http://127.0.0.1:<port>` origin, plus any private-network IP
(`192.168.x.x`, `10.x.x.x`, `172.16-31.x.x`) on any port — deliberately, so
the web demo works when `npm run dev` picks a non-default port, and when
you test from another device on your own LAN
(see README's "Testing from another device on your LAN"). It never matches
`https://`, and it rejects public/internet-routable origins outright —
`api/tests/test_cors.py` pins both the allowed cases and the rejection
boundary (an IP one digit outside the private ranges, or the right IP over
the wrong scheme, is still rejected). If you ever run this API bound to a
public interface or behind a public hostname, this CORS policy is not
sufficient for that — it was never designed to be.

## Reporting a vulnerability

Please report privately via
[GitHub's private security advisory feature](https://github.com/kvemugennexusai/forgeway/security/advisories/new)
rather than opening a public issue. Given the scope above, most reports
will likely be about the web demo or the API server when run outside its
intended local/LAN context — that's still useful to know about, so please
report it.

**Expected response time:** within 5 business days for an initial
acknowledgment. This is a technical preview maintained without a
dedicated security team, so please be patient beyond that — you will get
a response.
