#!/usr/bin/env python3
"""Read-only GitHub credential and project identity preflight; never prints tokens."""
import argparse
import json
import os
import shutil
import subprocess


def run(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None, "command_unavailable_or_timed_out"
    if result.returncode:
        # Do not forward arbitrary CLI stderr: credentials may appear in diagnostics.
        return None, "command_failed"
    return result.stdout, None


def api(endpoint):
    output, error = run(["gh", "api", endpoint])
    if error:
        return None, error
    try:
        value = json.loads(output)
    except (TypeError, ValueError):
        return None, "invalid_json_response"
    if not isinstance(value, dict):
        return None, "unexpected_response_shape"
    return value, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=".")
    parser.add_argument("--repo", help="Explicit owner/repository to inspect")
    args = parser.parse_args()
    result = {
        "gh_available": bool(shutil.which("gh")),
        "credential_selection": "GH_TOKEN" if os.environ.get("GH_TOKEN") else
            "GITHUB_TOKEN" if os.environ.get("GITHUB_TOKEN") else "stored_gh_credentials",
        "repository_creation": "unverified_requires_actual_create_operation",
    }
    email, email_error = run(["git", "-C", args.project, "config", "user.email"])
    result["project_commit_email_matches"] = not email_error and email.strip() == "builder@sapsynk.com"
    if result["gh_available"]:
        user, error = api("user")
        result["authentication"] = {"status": "failed", "reason": error} if error else {
            "status": "authenticated", "login": user.get("login")}
        if args.repo:
            parts = args.repo.split("/")
            if len(parts) != 2 or any(not p or not all(c.isalnum() or c in "-_." for c in p) for p in parts):
                parser.error("--repo must be owner/repository")
            repo, error = api("repos/" + args.repo)
            result["repository"] = {"status": "failed", "reason": error} if error else {
                "name": repo.get("full_name"), "user_permissions": repo.get("permissions"),
                "note": "User repository role is not the token's permission grant."}
        installations, error = api("user/installations")
        if not error and isinstance(installations.get("installations"), list):
            result["app_installations"] = [
                {"account": item.get("account", {}).get("login"),
                 "repository_selection": item.get("repository_selection"),
                 "permissions": item.get("permissions")}
                for item in installations["installations"]
                if isinstance(item, dict) and isinstance(item.get("account"), dict)
            ]
        elif error:
            result["app_installations"] = {"status": "unavailable", "reason": error}
    print(json.dumps(result, indent=2))
    return 0 if result.get("authentication", {}).get("status") == "authenticated" and result["project_commit_email_matches"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
