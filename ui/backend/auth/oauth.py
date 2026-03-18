"""OAuth provider client setup (Google, Microsoft)."""

import os
from typing import Optional

from httpx_oauth.clients.google import GoogleOAuth2
from httpx_oauth.clients.microsoft import MicrosoftGraphOAuth2

# ---------------------------------------------------------------------------
# Google OAuth2
# ---------------------------------------------------------------------------
GOOGLE_CLIENT_ID = os.environ.get("OAUTH_GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("OAUTH_GOOGLE_CLIENT_SECRET", "")

google_oauth_client: Optional[GoogleOAuth2] = None
if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    google_oauth_client = GoogleOAuth2(
        GOOGLE_CLIENT_ID,
        GOOGLE_CLIENT_SECRET,
        scopes=["openid", "email", "profile"],
    )

# ---------------------------------------------------------------------------
# Microsoft OAuth2
# ---------------------------------------------------------------------------
MICROSOFT_CLIENT_ID = os.environ.get("OAUTH_MICROSOFT_CLIENT_ID", "")
MICROSOFT_CLIENT_SECRET = os.environ.get("OAUTH_MICROSOFT_CLIENT_SECRET", "")
MICROSOFT_TENANT_ID = os.environ.get("OAUTH_MICROSOFT_TENANT_ID", "common")

microsoft_oauth_client: Optional[MicrosoftGraphOAuth2] = None
if MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET:
    microsoft_oauth_client = MicrosoftGraphOAuth2(
        MICROSOFT_CLIENT_ID,
        MICROSOFT_CLIENT_SECRET,
        tenant=MICROSOFT_TENANT_ID,
        scopes=["openid", "email", "profile", "User.Read"],
    )
