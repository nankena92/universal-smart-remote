"""Streaming-app ids per brand (CONTRACTS.md §1).

``None`` means "no documented app id / not supported": ``launch_app`` must
return ``CommandResult(success=False, ...)``, never a guessed id.

Verification (2026-11-24, web search while implementing):
- Samsung Tizen ids (Netflix 3201907018807, Prime Video 3201910019365,
  YouTube 111299001912): homebridge-samsung-tizen application list
  (tavicu.github.io/homebridge-samsung-tizen/extra/applications.html),
  Home Assistant community thread on Samsung app launch, and the
  SamsungTVRemote app reference. All three ids confirmed by multiple
  independent sources. Note: the same sources list Disney+ on Samsung as
  3201901017640, but CONTRACTS.md §1 specifies ``None`` for it, so it is
  left as ``None`` here per the contract.
- Roku channel ids (Netflix 12, Prime Video 13, YouTube 837,
  Disney+ 291097): confirmed by a real ``/query/apps`` XML dump
  (virtu.is), the ``stuartskelton/roku`` Go package constants, and the
  mcp-remote-control app table.
- LG webOS ids (netflix, amazon, youtube): ioBroker.lgtv README documents
  launching ``netflix`` / ``youtube`` / ``amazon`` (``prime`` also opens
  Prime Video on some sets); lgtvremote-cli documents shortcuts
  ``netflix`` -> ``netflix``, ``amazon``/``prime`` -> ``amazon``; lgtv2
  documents ``ssap://system.launcher/launch {id: 'netflix'}``.
  Caveat: the canonical webOS app id for YouTube is
  ``youtube.leanback.v4`` (lgtv2, LGWebOSRemote); ``youtube`` is kept here
  because it is the documented launch identifier used by ioBroker.lgtv —
  if it fails on a set, try ``youtube.leanback.v4``. LG Disney+ is ``None``
  per CONTRACTS.md §1 (sources list ``com.disney.disneyplus-prod``).
- Android TV / Fire TV package names (com.netflix.ninja,
  com.amazon.amazonvideo.livingroom, com.google.android.youtube.tv,
  com.disney.disneyplus): Home Assistant androidtv_remote docs
  ("Launching apps" application-ID table), corroborated by the
  Shield/Harmony app-mapping blueprint and the tv-remote docs.
No non-None id in this table had to be demoted.
"""

from __future__ import annotations

from typing import Optional

STREAMING_APPS = {
    "netflix": {"roku": "12", "samsung": "3201907018807", "lg": "netflix",
                "androidtv": "com.netflix.ninja", "firetv": "com.netflix.ninja",
                "sony": None, "tcl": None},
    "prime":   {"roku": "13", "samsung": "3201910019365", "lg": "amazon",
                "androidtv": "com.amazon.amazonvideo.livingroom",
                "firetv": "com.amazon.amazonvideo.livingroom",
                "sony": None, "tcl": None},
    "youtube": {"roku": "837", "samsung": "111299001912", "lg": "youtube",
                "androidtv": "com.google.android.youtube.tv",
                "firetv": "com.google.android.youtube.tv",
                "sony": None, "tcl": None},
    "disney":  {"roku": "291097", "samsung": None, "lg": None,
                "androidtv": "com.disney.disneyplus",
                "firetv": "com.disney.disneyplus",
                "sony": None, "tcl": None},
}


def get_app_id(app: str, brand: str) -> Optional[str]:
    """Return the brand-specific app id for a streaming app, or None.

    ``app`` is one of ``netflix`` | ``prime`` | ``youtube`` | ``disney``.
    Returns None for unknown apps, unknown brands, and brands with no
    documented id (callers must treat None as "not supported", never guess).
    For ``tcl``, resolve through the delegated adapter's brand (see
    CONTRACTS.md §1); this helper returns None for ``tcl`` directly.
    """
    entry = STREAMING_APPS.get(app)
    if entry is None:
        return None
    return entry.get(brand)
