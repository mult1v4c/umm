# UMM - Unified (Unreasonable) Media Manager

> *Because managing your media manually is... unreasonable.*

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg?style=flat&logo=python)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg?style=flat)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Active-brightgreen.svg?style=flat)](#)
![Stability-experimental](https://img.shields.io/badge/Stability-Experimental-orange.svg)

![Preview](preview.png)

UMM (Unified Media Manager) is a modular Python-based tool that automates fetching, downloading, and organizing movie trailers, complete with placeholder and backdrop generation.

## Why UMM...
I used to have a bunch of PowerShell scripts to help organize my growing movie collection.  But as I kept adding new scripts for each task I wanted automated, it became cumbersome to maintain.

That’s when I decided to combine everything into one modular tool — and UMM was born.

There are still features yet to be implemented, but I’m happy to share a stable version.  This is a work in progress, so expect improvements and changes over time.


## Features
- Checks the latest movies from TMDB and downloads trailers from YouTube using `yt-dlp`
- Smart caching for TMDB API calls (reduces redundant network requests)
- Generate placeholder assets using `ffmpeg` (explained below)
- Concurrent processing with thread-safe task handling
- Organize library with recognizable naming convention `Movie Title (2000)`
- Dry-run mode for safely previewing actions before making any changes

## Requirements
- Python 3.10+
- FFmpeg (must be accessible in PATH)
- yt-dlp (must be accessible in PATH)

## Installation
Clone the repository and install dependencies:
```bash
git clone https://github.com/mult1v4c/umm.git
cd umm
pip install -r requirements.txt
```

## Quick Options

Use `--help` for a full list of available commands.

| **Option**                             | **Description**                         |
| -------------------------------------- | --------------------------------------- |
| `--year`, `--year-start`, `--year-end` | Define which years to process.          |
| `--all`                                | Run all stages (default).               |
| `--download`                           | Only download trailers.                 |
| `--placeholders`, `--backdrops`        | Only generate assets.                   |
| `--dry-run`                            | Simulate actions without writing files. |
| `--count`                              | Limit number of downloads.              |
| `--clear-cache`, `--no-cache`          | Manage TMDB API cache.                  |
| `--report`, `--export-list`            | Output processed data.                  |
| `--verbose`, `--quiet`                 | Control logging level.                  |


## Example Usage

**Fetch and download trailers for a specific year**
```
python umm.py --year 2025
```

**Check available trailers from 2020 to 2025**
```
python umm.py --year-start 2020 --year-end 2025 --dry-run
```

**Download a limited number of trailers**
```
python umm.py --year 2025 --count 5
```

## Configuration
Runtime options can be set via CLI flags or the generated `config.json`.

**First generate config**
```
python umm.py
```

| Option                   | Description                                       |
| ------------------------ | ------------------------------------------------- |
| `TMDB_API_KEY`           | Your TMDB API key (required)                      |
| `DOWNLOAD_FOLDER`        | Base folder for movies and trailers               |
| `CACHE_FOLDER`           | Local cache directory for TMDB data               |
| `MAX_DOWNLOAD_WORKERS`   | Number of parallel download threads               |
| `MAX_FFMPEG_WORKERS`     | Number of parallel FFmpeg tasks                   |
| `CREATE_BACKDROP`        | Whether to generate backdrop images               |
| `PLACEHOLDER_DURATION`   | Duration (in seconds) of black placeholder videos |
| `PLACEHOLDER_RESOLUTION` | Output resolution for generated assets            |


## Jellyfin Integration
I use Jellyfin with several plugins and one of which is [Cinema Mode](https://github.com/CherryFloors/jellyfin-plugin-cinemamode). It uses local trailers from a library within Jellyfin and plays them before your selected media (just like in the theaters). UMM's role in this setup is scanning TMDB for upcoming movie releases and downloads its trailers to your selected folder.

Since Jellyfin does not recognize trailers as actual movies, you need placeholder files with the same name for it to properly display in your library. In this case, UMM generates a 1-second video file and names it accordingly. This way, the library may now be used with cinema mode. This is explained better in this [Reddit post](https://www.reddit.com/r/JellyfinCommunity/comments/1mm9n6c/bringing_movie_theater_magic_to_jellyfin_my/).

I've also designed UMM to generate a black `backdrop.jpg` for the trailers. The reason being Cinema Mode has a quick delay between playing the next trailer and it shows the backdrop image for a split second. Using this black backdrop enhances the immersion instead of a quick glance of the actual backdrop generated by Jellyfin.

Here's a sample directory structure:
```
📁 Media/Trailers/
│
└── Oppenheimer (2023)/
    ├── Oppenheimer (2023)-trailer.mp4
    ├── Oppenheimer (2023).mp4
    └── backdrop.jpg
```

## Future Plans
- [ ] Fetch movie data and trailers of your existing library
- [ ] Improve TMDB queries since current version only checks for 3 pages per year (can be changed in config)
- [ ] Improve trailer selection logic
- [ ] Add option to organize existing movie library
- [ ] Menu interface for ease of use
- [ ] Granular trailer selection options