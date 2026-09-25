"""Endpoints and constants for Lantmäteriet's National Geodata Platform (NGP)."""

from __future__ import annotations

from dataclasses import dataclass

PLUGIN_NAME = "LM-NGP Downloader"
SETTINGS_PREFIX = "ngp_downloader"

# All NGP reference objects default to SWEREF 99 TM (not WGS 84 as in plain STAC).
NGP_CRS = "EPSG:3006"

SEARCH_PATH = "/distribution/geodatakatalog/sokning/v1/{dataset}/{version}"
DOWNLOAD_PATH = "/distribution/geodatakatalog/nedladdning/v1"


@dataclass(frozen=True)
class Environment:
    key: str
    label: str
    api_url: str
    token_url: str


ENVIRONMENTS = {
    "production": Environment(
        key="production",
        label="Produktion",
        api_url="https://api.lantmateriet.se",
        token_url="https://apimanager.lantmateriet.se/oauth2/token",
    ),
    "verification": Environment(
        key="verification",
        label="Verifikation",
        api_url="https://api-ver.lantmateriet.se",
        token_url="https://apimanager-ver.lantmateriet.se/oauth2/token",
    ),
}
DEFAULT_ENVIRONMENT = "production"


def search_base_url(env_key: str, dataset_id: str, version: str) -> str:
    env = ENVIRONMENTS[env_key]
    return env.api_url + SEARCH_PATH.format(dataset=dataset_id, version=version)
