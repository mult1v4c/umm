import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import List, Set

logger = logging.getLogger("media_manager")

class JunkService:
    def __init__(self, cache_folder: str, video_extensions: Set[str], library_folder: Path):
        self.cache_path = Path(cache_folder).expanduser() / "junk_cache.json"
        self.video_extensions = video_extensions
        self.library_folder = library_folder # Renamed from download_folder

    def _is_normalized_filename(self, filename_stem: str) -> bool:
        # Checks if a filename matches the 'Title (Year)' format
        return bool(re.search(r'^.+\s\(\d{4}\)$', filename_stem))

    def _scan_for_videos(self) -> List[Path]:
        # Scans the movie library for all video files
        return [
            p for p in self.library_folder.rglob("*") # Use library_folder
            if p.is_file() and p.suffix.lower() in self.video_extensions
        ]

    def _tokenize_filename(self, filename: str) -> List[str]:
        # Breaks a filename down into a list of potential junk words (tokens)
        name = Path(filename).stem
        name = re.sub(r"[\._\[\]\(\)-]", " ", name)
        tokens = [token.lower() for token in name.split()]
        return [token for token in tokens if len(token) > 2 and not token.isdigit()]


    def build_junk_cache(self, force_rebuild: bool = False) -> Set[str]:
        # Analyzes ONLY unnormalized video filenames to dynamically build a set of common junk words.
        if not force_rebuild and self.cache_path.exists():
            try:
                with self.cache_path.open("r", encoding="utf-8") as f:
                    return set(json.load(f))
            except (json.JSONDecodeError, IOError):
                logger.warning("[yellow]Junk cache is corrupt. Rebuilding.[/yellow]")

        logger.info("Building junk word cache from library filenames...")
        video_files = self._scan_for_videos()

        if len(video_files) < 10:
            logger.info("Library is too small to build a reliable junk cache. Using default patterns.")
            return set()

        all_tokens = []
        unnormalized_file_count = 0
        for file_path in video_files:
            if self._is_normalized_filename(file_path.stem):
                continue

            unnormalized_file_count += 1
            unique_tokens_per_file = set(self._tokenize_filename(file_path.name))
            all_tokens.extend(list(unique_tokens_per_file))

        if unnormalized_file_count < 5:
            logger.info(f"Not enough unnormalized files ({unnormalized_file_count}) to build a reliable junk cache.")
            return set()

        token_counts = Counter(all_tokens)
        junk_words = set()

        junk_threshold = unnormalized_file_count * 0.2
        for token, count in token_counts.items():
            if count > junk_threshold and count > 1:
                junk_words.add(token)

        if junk_words:
            logger.info(f"Identified {len(junk_words)} common junk words from {unnormalized_file_count} files (e.g., {list(junk_words)[:3]}). Saving to cache.")
            try:
                with self.cache_path.open("w", encoding="utf-8") as f:
                    json.dump(list(junk_words), f, indent=2)
            except IOError as e:
                logger.error(f"Failed to save junk cache: {e}")
        else:
            logger.info(f"No recurring junk words were identified across the {unnormalized_file_count} unnormalized files.")

        return junk_words