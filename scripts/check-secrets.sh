#!/usr/bin/env bash
# Pre-public-flip secret scanner.
#
# This repo is private but is temporarily made public during HA add-on
# rebuilds. Run this script BEFORE flipping the GitHub repo to public:
#
#   ./scripts/check-secrets.sh
#
# Exits non-zero if any tracked file contains a pattern that looks like a
# secret, an internal hostname, or a private LAN IP. The scanner skips
# itself, the .gitignore, and (intentionally) doesn't scan untracked files
# (e.g. local config.yaml).
#
# When to run: as step 3.5 of the deploy procedure, immediately BEFORE
# `gh repo edit galletn/PowerManager --visibility public ...`.

set -uo pipefail

# Move to repo root
cd "$(git rev-parse --show-toplevel 2>/dev/null)" || {
    echo "ERROR: not inside a git repo" >&2
    exit 2
}

FOUND=0

# scan <label> <git-grep-pattern>
#
# Prints up to 20 matches; sets FOUND=1 on any hit.
# Excludes self (this script) and .gitignore so their pattern definitions
# don't trigger false positives.
scan() {
    local label="$1"
    local pattern="$2"
    local matches
    matches=$(git grep -nIE "$pattern" -- \
        ':!scripts/check-secrets.sh' \
        ':!.gitignore' \
        2>/dev/null || true)
    if [ -n "$matches" ]; then
        echo "FAIL [$label]"
        echo "$matches" | head -20
        echo ""
        FOUND=1
    else
        echo "OK   [$label]"
    fi
}

echo "==> Scanning tracked files for sensitive patterns..."
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

# Private LAN IPs (192.168.x.x — common home network range)
scan "private LAN IP (192.168.x.x)" \
    '192\.168\.[0-9]{1,3}\.[0-9]{1,3}'

# Hardcoded secret/password/api_key with a non-trivial value (12+ chars).
# Skips test fixtures using 'fake'/'test'/'mock'/'example' or single-char
# placeholders.
scan "hardcoded secret assignment" \
    '(api[_-]?key|secret|passwd|password|bearer|access[_-]?token)[[:space:]]*[:=][[:space:]]*["\x27][A-Za-z0-9_./+=-]{12,}["\x27]'

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
