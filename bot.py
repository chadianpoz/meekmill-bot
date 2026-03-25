#!/usr/bin/env python3
"""Twitter bot that tweets every time meekmill24 pushes a commit to GitHub."""

import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import tweepy

# --- Config ---
GITHUB_USER = "meekmill24"
STATE_FILE = Path(__file__).parent / "tweeted_commits.json"
MAX_TWEET_LEN = 280


def get_twitter_client() -> tweepy.Client:
    """Authenticate with Twitter API v2."""
    keys = {
        "TWITTER_API_KEY": os.environ.get("TWITTER_API_KEY"),
        "TWITTER_API_SECRET": os.environ.get("TWITTER_API_SECRET"),
        "TWITTER_ACCESS_TOKEN": os.environ.get("TWITTER_ACCESS_TOKEN"),
        "TWITTER_ACCESS_SECRET": os.environ.get("TWITTER_ACCESS_SECRET"),
    }
    missing = [k for k, v in keys.items() if not v]
    if missing:
        print(f"ERROR: Missing env vars: {', '.join(missing)}")
        sys.exit(1)
    return tweepy.Client(
        consumer_key=keys["TWITTER_API_KEY"],
        consumer_secret=keys["TWITTER_API_SECRET"],
        access_token=keys["TWITTER_ACCESS_TOKEN"],
        access_token_secret=keys["TWITTER_ACCESS_SECRET"],
    )


def load_tweeted() -> set:
    """Load set of already-tweeted commit SHAs."""
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_tweeted(tweeted: set):
    """Persist tweeted commit SHAs (keep last 500 to avoid unbounded growth)."""
    recent = sorted(tweeted)[-500:]
    STATE_FILE.write_text(json.dumps(recent, indent=2))


def get_repos() -> list[str]:
    """Fetch all public repo full names for the user."""
    headers = _gh_headers()
    resp = requests.get(
        f"https://api.github.com/users/{GITHUB_USER}/repos",
        headers=headers,
        params={"per_page": 100},
        timeout=15,
    )
    resp.raise_for_status()
    return [r["full_name"] for r in resp.json()]


def get_recent_commits(repo: str, since: str | None = None) -> list[dict]:
    """Fetch recent commits from a repo."""
    headers = _gh_headers()
    params = {"per_page": 30}
    if since:
        params["since"] = since
    resp = requests.get(
        f"https://api.github.com/repos/{repo}/commits",
        headers=headers,
        params=params,
        timeout=15,
    )
    if resp.status_code == 409:  # empty repo
        return []
    resp.raise_for_status()
    return resp.json()


def _gh_headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


TEMPLATES = [
    lambda repo, msg: f'BREAKING: Meek Mill pushed to {repo} — "{msg}"',
    lambda repo, msg: f'Meek Mill just committed:\n\n"{msg}"\n\nRepo: {repo}',
    lambda repo, msg: f'New code from Meek Mill in {repo}:\n\n"{msg}"',
    lambda repo, msg: f'Meek Mill is coding again.\n\n"{msg}"\n\n— {repo}',
]


def format_tweet(commit: dict, repo_name: str) -> str:
    """Format a tweet for a single commit using a random template."""
    msg = commit["commit"]["message"].split("\n")[0]
    url = commit["html_url"]
    short_repo = repo_name.split("/")[-1]

    template = random.choice(TEMPLATES)
    # Trim message to fit within tweet limit with URL
    suffix = f"\n\n{url}"
    body = template(short_repo, msg)
    max_body = MAX_TWEET_LEN - len(suffix)
    if len(body) > max_body:
        # Recalculate with truncated message
        over = len(body) - max_body + 3
        msg = msg[:-over] + "..."
        body = template(short_repo, msg)

    return f"{body}{suffix}"


def run():
    """Main: fetch commits across all repos, tweet new ones."""
    now = datetime.now(timezone.utc).isoformat()
    print(f"[{now}] Checking for new commits from {GITHUB_USER}...")

    tweeted = load_tweeted()
    repos = get_repos()
    new_commits = []

    for repo in repos:
        commits = get_recent_commits(repo)
        for c in commits:
            # Only tweet commits authored by meekmill24
            author = c.get("author")
            if author and author.get("login", "").lower() == GITHUB_USER.lower():
                if c["sha"] not in tweeted:
                    new_commits.append((c, repo))

    if not new_commits:
        print("No new commits.")
        return

    # Oldest first so tweets are chronological
    new_commits.reverse()
    print(f"Found {len(new_commits)} new commit(s).")

    client = get_twitter_client()

    for commit, repo in new_commits:
        tweet_text = format_tweet(commit, repo)
        try:
            client.create_tweet(text=tweet_text)
            msg_preview = commit["commit"]["message"].split("\n")[0][:60]
            print(f"  Tweeted: {commit['sha'][:7]} - {msg_preview}")
            tweeted.add(commit["sha"])
            time.sleep(2)  # pace tweets
        except tweepy.TweepyException as e:
            print(f"  Failed to tweet {commit['sha'][:7]}: {e}")

    save_tweeted(tweeted)
    print("Done.")


if __name__ == "__main__":
    run()
