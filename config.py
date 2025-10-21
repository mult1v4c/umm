import json
import logging
import sys
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger("media_manager")
CONFIG_FILE_PATH = Path("config.json")

DEFAULT_CONFIG = {
    "TMDB_API_KEY": "YOUR_API_KEY",
    "MOVIE_LIBRARY": "~/Movies",
    "DOWNLOAD_FOLDER": "~/Downloads/UMM_New_Trailers",
    "CACHE_FOLDER": "~/.cache/umm",
    "YT_DLP_PATH": "yt-dlp",
    "FFMPEG_PATH": "ffmpeg",
    "START_YEAR": 2025,
    "END_YEAR": 2026,
    "PAGES_PER_YEAR": 5,
    "MAX_DOWNLOAD_WORKERS": 4,
    "MAX_FFMPEG_WORKERS": 4,
    "CREATE_BACKDROP": False,
    "PLACEHOLDER_DURATION": 3,
    "PLACEHOLDER_RESOLUTION": "1920x1080",
    "TMDB_FILTERS": {
        "sort_by": "popularity.desc",
        "with_original_language": "en",
        "include_adult": "false",
        "include_video": "false",
    },
}

KNOWN_FAILURES_FILENAME = "known_failures.json"
TRAILER_SUFFIX = "-trailer"
BACKDROP_FILENAME = "backdrop.jpg"
STATUS_FILENAME = "umm_status.json"

# TMDB
BASE_URL = "https://api.themoviedb.org/3"
DISCOVER_URL = f"{BASE_URL}/discover/movie"


def load_config() -> Dict[str, Any]:
    if not CONFIG_FILE_PATH.exists():
        try:
            with CONFIG_FILE_PATH.open("w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=4)
            logger.info(f"Created default config file at [cyan]{CONFIG_FILE_PATH.resolve()}[/cyan]")
            logger.info("Please edit this file to add your TMDB_API_KEY.")
            sys.exit(0)
        except IOError as e:
            logger.error(f"Failed to create config file: {e}")
            sys.exit(1)

    try:
        with CONFIG_FILE_PATH.open("r", encoding="utf-8") as f:
            config_data = json.load(f)
            # --- This is a new "migration" check ---
            # It checks if any keys from the default config are missing
            # If so, it adds them and saves the file.
            missing_keys = False
            for key, value in DEFAULT_CONFIG.items():
                if key not in config_data:
                    config_data[key] = value
                    missing_keys = True

            if missing_keys:
                logger.warning("[yellow]Old config file detected. Adding new default settings...[/yellow]")
                save_config(config_data)

            return config_data

    except (IOError, json.JSONDecodeError) as e:
        logger.error(f"Failed to read or parse config file: {e}")
        sys.exit(1)

def save_config(config_data: Dict[str, Any]):
    try:
        with CONFIG_FILE_PATH.open("w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)
        logger.info(f"Successfully updated [cyan]{CONFIG_FILE_PATH.resolve()}[/cyan]")
    except IOError as e:
        logger.error(f"Failed to save config file: {e}")