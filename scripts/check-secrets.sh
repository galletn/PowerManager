#!/usr/bin/env bash
# Pre-public-flip secret scanner.
#
# This repo is private but is temporarily made public during HA add-on
# rebuilds. Run this script BEFORE flipping the GitHub repo to public:
#
#   ./scripts/check-secrets.sh
#
# Exits non-zero if any tracked file at HEAD contains a pattern that
# looks like a secret, an internal hostname, or a private LAN IP. Scans
# HEAD (the commit `git push` will publish) — not the working tree —
# so scan target matches push target. Skips this script and .gitignore.
#
# When to run: as step 3.5 of the deploy procedure, immediately BEFORE
# `gh repo edit galletn/PowerManager --visibility public ...`.

set -euo pipefail

# Move to repo root. Capture the path first so an empty rev-parse output
# doesn't silently degrade to a no-op `cd ""` when run outside a repo.
topdir=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "ERROR: not inside a git repo" >&2
    exit 2
}
if [ -z "$topdir" ]; then
    echo "ERROR: not inside a git repo" >&2
    exit 2
fi
cd "$topdir" || {
    echo "ERROR: failed to cd to $topdir" >&2
    exit 2
}

FOUND=0

# scan <label> <git-grep-pattern>
#
# Scans the HEAD commit (what `git push` will publish), NOT the working
# tree, so the scan target matches the push target.
# Distinguishes git-grep exit 1 (no match — OK) from exit ≥2 (error,
# e.g. malformed regex — must FAIL rather than silently pass).
scan() {
    local label="$1"
    local pattern="$2"
    local matches=""
    local status=0
    matches=$(git grep -nIE "$pattern" HEAD -- \
        ':!scripts/check-secrets.sh' \
        ':!.gitignore') || status=$?
    if [ "$status" -ge 2 ]; then
        echo "ERROR [$label] git grep exit $status (malformed regex or git error)"
        FOUND=1
        return
    fi
    if [ -n "$matches" ]; then
        echo "FAIL [$label]"
        echo "$matches" | head -20
        echo ""
        FOUND=1
    else
        echo "OK   [$label]"
    fi
}

echo "==> Scanning HEAD for sensitive patterns..."
echo ""

# Home Assistant Long-Lived Access Token (JWT format)
# JWTs are 3 base64url-encoded segments separated by '.'. The HA token
# always starts with 'eyJ' (the base64 of '{"a'). 50+ chars total is a
# safe minimum to avoid matching short legitimate base64 strings.
scan "HA token (JWT)" \
    'eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}'

# Specific operator hostname
scan "operator-specific hostname" \
    'gallet\.duckdns\.org'

# Generic DuckDNS hostname (any subdomain — flags accidental re-add)
scan "generic DuckDNS hostname" \
    '[a-z0-9-]+\.duckdns\.org'

# Private LAN IPs — full RFC1918 ranges (10/8, 172.16-31/12, 192.168/16).
# CLAUDE.md advertises this scanner as catching "private IPs"; the regex
# must cover all three reserved ranges, not just the home-LAN /16.
scan "private LAN IP (RFC1918)" \
    '(10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|172\.(1[6-9]|2[0-9]|3[0-1])\.[0-9]{1,3}\.[0-9]{1,3}|192\.168\.[0-9]{1,3}\.[0-9]{1,3})'

# Hardcoded secret/password/api_key with a non-trivial value (12+ chars).
# Quoted form: `password = "supersecret"` / `api_key: 'abc...'`
scan "hardcoded secret assignment (quoted)" \
    '(api[_-]?key|secret|passwd|password|bearer|access[_-]?token)[[:space:]]*[:=][[:space:]]*["\x27][A-Za-z0-9_./+=-]{12,}["\x27]'

# Unquoted form: shell-style `PASSWORD=abc...` or `API_KEY=value` with no
# surrounding quotes — the high-risk shell-script case the quoted regex
# misses.
scan "hardcoded secret assignment (unquoted)" \
    '(api[_-]?key|secret|passwd|password|bearer|access[_-]?token)[[:space:]]*=[[:space:]]*[A-Za-z0-9_./+=-]{12,}'

# AWS-style access keys
scan "AWS access key" \
    'AKIA[0-9A-Z]{16}'

# Generic Bearer tokens in code/text (not in test fixtures with 'fake')
scan "Bearer token literal" \
    'Bearer[[:space:]]+[A-Za-z0-9_.-]{20,}'

# Sudo password '1234' assignment (specific to this operator's memory)
scan "weak sudo password" \
    'sudo[[:space:]]*(pw|password|passwd)[[:space:]]*[:=][[:space:]]*["\x27]?1234'

echo ""
if [ "$FOUND" -eq 0 ]; then
    echo "==> All scans clean. Safe to flip the repo to public."
    exit 0
else
    echo "==> One or more patterns matched. Review the FAIL entries above"
    echo "    BEFORE making the repo public. Either fix the source file,"
    echo "    add the pattern's file to .gitignore, or run"
    echo "    'git rm --cached <file>' if it was committed accidentally."
    exit 1
fi
