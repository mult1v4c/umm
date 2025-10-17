import json
from pathlib import Path
from typing import Dict, Any

# --- Constants ---
BASE_URL = "https://api.themoviedb.org/3"
DISCOVER_URL = f"{BASE_URL}/discover/movie"
BACKDROP_FILENAME = "backdrop.jpg"
TRAILER_SUFFIX = "-trailer"
KNOWN_FAILURES_FILENAME = "known_failures.json"

# --- Default Config ---
DEFAULT_CONFIG: Dict[str, Any] = {
    "TMDB_API_KEY": "YOUR_API_KEY",
    "START_YEAR": 2024,
    "END_YEAR": 2025,
    "PAGES_PER_YEAR": 3,
    "TMDB_FILTERS": {
        "language": "en-US",
        "sort_by": "popularity.desc",
        "include_adult": "false",
        "include_video": "false",
        "vote_count.gte": 50,
        "vote_average.gte": 4,
        "with_original_language": "en",
        "without_genres": "10751"
    },
    "DOWNLOAD_FOLDER": r"X:\Media\Trailers",
    "CACHE_FOLDER": ".cache",
    "YT_DLP_PATH": "yt-dlp",
    "FFMPEG_PATH": "ffmpeg",
    "MAX_DOWNLOAD_WORKERS": 4,
    "MAX_FFMPEG_WORKERS": 2,
    "CREATE_BACKDROP": True,
    "PLACEHOLDER_DURATION": 1,
    "PLACEHOLDER_RESOLUTION": "1920x1080",
    "LOG_LEVEL": "INFO",
    "SIMULATE_ERRORS_PROB": 0.0
}

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.json"

def load_config() -> Dict:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            try:
                user_config = json.load(f)
            except json.JSONDecodeError:
                print(f"ERROR: Could not parse {CONFIG_PATH}. Please check for syntax errors.")
                return DEFAULT_CONFIG.copy()

        merged_config = DEFAULT_CONFIG.copy()
        merged_config.update(user_config)

        if "TMDB_FILTERS" in user_config:
            merged_filters = DEFAULT_CONFIG["TMDB_FILTERS"].copy()
            merged_filters.update(user_config["TMDB_FILTERS"])
            merged_config["TMDB_FILTERS"] = merged_filters

        return merged_config
    else:
        with CONFIG_PATH.open("w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        print(f"INFO: Default config.json created at {CONFIG_PATH}. Please edit it with your TMDB API key.")
        return DEFAULT_CONFIG.copy()