import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

import requests
from config import BASE_URL, DISCOVER_URL

logger = logging.getLogger("media_manager")

class TMDbService:

    def __init__(self, api_key: str, cache_folder: str, pages_per_year: int, tmdb_filters: Dict):
        self.api_key = api_key
        self.cache_folder = Path(cache_folder).expanduser()
        self.pages_per_year = pages_per_year
        self.tmdb_filters = tmdb_filters
        self.cache_folder.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_folder / "movies_cache.json"

    def fetch_movies(self, year_start: int, year_end: int, no_cache: bool, clear_cache: bool) -> List[Dict]:

        if clear_cache and self.cache_file.exists():
            self.cache_file.unlink()
            logger.info(f"Cleared persistent cache file: [yellow]{self.cache_file}[/yellow]")

        cached_movies_by_year: Dict[str, List[Dict]] = {}
        if not no_cache and self.cache_file.exists():
            try:
                with self.cache_file.open("r", encoding="utf-8") as f:
                    cached_movies_by_year = json.load(f)
            except json.JSONDecodeError:
                logger.warning("[yellow]Warning:[/] Cache file is corrupt. Starting fresh.")

        requested_years = list(range(year_start, year_end + 1))
        years_to_fetch = [str(y) for y in requested_years if str(y) not in cached_movies_by_year]
        years_from_cache = [str(y) for y in requested_years if str(y) in cached_movies_by_year]

        if years_from_cache:
            logger.info(f"Loaded data for year(s) [bold blue]{', '.join(years_from_cache)}[/bold blue] from [yellow]cache[/yellow].")

        if years_to_fetch:
            logger.info(f"Fetching new data for year(s) [bold blue]{', '.join(years_to_fetch)}[/bold blue] from TMDB API...")
            for year_str in years_to_fetch:
                year_movies = self._fetch_movies_for_year(int(year_str))
                cached_movies_by_year[year_str] = year_movies

            self._save_cache(cached_movies_by_year)

        all_movies = []
        for year in requested_years:
            all_movies.extend(cached_movies_by_year.get(str(year), []))

        return all_movies

    def _fetch_movies_for_year(self, year: int) -> List[Dict]:
        year_movies = []
        for page in range(1, self.pages_per_year + 1):
            params = self.tmdb_filters.copy()
            params.update({"api_key": self.api_key, "primary_release_year": year, "page": page})
            try:
                resp = requests.get(DISCOVER_URL, params=params, timeout=20)
                resp.raise_for_status()
                results = resp.json().get("results", [])
                if not results:
                    break
                year_movies.extend(results)
            except requests.RequestException as e:
                logger.warning(f"[yellow]Warning:[/] TMDB request failed for year {year}, page {page}: {e}")
                break
        return year_movies

    def _save_cache(self, data: Dict):
        try:
            with self.cache_file.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logger.info(f"Updated cache with new data.")
        except IOError as e:
            logger.error(f"Failed to write to cache file: {e}")

    def get_trailer_key(self, movie_id: int) -> Optional[str]:
        try:
            url = f"{BASE_URL}/movie/{movie_id}/videos"
            params = {"api_key": self.api_key}
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            videos = resp.json().get("results", [])

            youtube_videos = [v for v in videos if v.get("site") == "YouTube"]

            # Define priority order
            priorities = {
                ("Trailer", True): 1,  # Official Trailer
                ("Trailer", False): 2, # Unofficial Trailer
                ("Teaser", True): 3,   # Official Teaser
                ("Teaser", False): 4,  # Unofficial Teaser
            }

            best_video = None
            lowest_priority = float('inf')

            for v in youtube_videos:
                v_type = v.get("type")
                v_official = v.get("official", False)
                priority = priorities.get((v_type, v_official))

                if priority is not None and priority < lowest_priority:
                    best_video = v
                    lowest_priority = priority

            return best_video.get("key") if best_video else None

        except requests.RequestException:
            logger.warning(f"Failed to fetch trailer key for movie ID {movie_id}.")
            return None