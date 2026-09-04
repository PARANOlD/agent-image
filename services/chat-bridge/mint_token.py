"""CLI: print a fresh GitHub App installation token to stdout.

Run inside the chat-bridge image (it already has PyJWT/requests) via
scripts/mint-github-app-token.sh, which captures the output into .env's
GITHUB_TOKEN for the openhands container's git operations.
"""
import os
import sys

from github_app_auth import GitHubAppAuth

if __name__ == "__main__":
    auth = GitHubAppAuth(
        app_id=os.environ["GITHUB_APP_ID"],
        private_key_path=os.environ["GITHUB_APP_PRIVATE_KEY_PATH"],
        installation_id=os.environ["GITHUB_APP_INSTALLATION_ID"],
    )
    print(auth.get_token(), end="")
    sys.stderr.write("Token minted (valid ~1hr).\n")
