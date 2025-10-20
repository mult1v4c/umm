### **The Finalized UMM Workflow**

The new UMM is designed to be a robust, user-friendly, and safe media management tool. Its operation is centered around a clear menu-driven interface and a philosophy of never performing a file operation without user awareness.

#### **The Main Interface & Core Principles**

Upon first intialization `python umm.py`, it generates `config.json` and asks the user to make changes if necessary (needed for API, default options etc.). The tool will launch into a persistent menu.

All operations that modify files will respect the Dry-Run mode.

  * **Interactive Dry-Run Mode**: The menu will feature a toggle for Dry-Run mode. When **ON**, any action that would normally write, rename, move, or delete files will instead simulate the action and log the intended changes to the console.
  * **Dry-Run Confirmation**: After a successful dry run simulation, the script will ask for user confirmation before proceeding. This provides a crucial safety net. The flow is: **Select Action -\> Simulate Changes -\> Review Log -\> Confirm -\> Execute Changes**.

**Example Menu:**
```
[add ascii art]
UMM - Unified Media Manager
-----------------------------------
[1] Sanitize & Catalog Movie Library
[2] Fetch Trailers for Existing Movies
[3] Fetch Upcoming Movie Trailers
[4] Sync Trailers with Movie Library
[5] Library Status
[6] Settings and Utilities
[0] Exit
-----------------------------------
[D] Toggle Dry-Run Mode (Currently: ON)
```
-----

### **Option `[1]`: Sanitize & Catalog Movie Library**

**Goal**: To turn your messy `/Movies` folder into a perfectly organized and cataloged library. This is the foundational step.

**Flow**:

1.  **Initiate**: User selects option `[1]`. The script initializes three empty lists to track issues: `unparseable_files`, `unmatched_files`, and `duplicate_files`.
2.  **Scan**: The script recursively scans the `/Movies` directory to find all video files, ignoring any known trailer files.
3.  **Process Loop**: For each file found:
    1. **Parse**: It attempts to extract a `title` and `year` using its regex logic.
    2. **Match**: If parsing is successful, it queries the TMDB API to find a definitive match.
    3. **Catalog**: If a match is found, it adds the movie's details (TMDB ID, official title, file path) to a temporary list. It checks for duplicates at this stage.
    4. **Simulate/Execute**: The script determines the new, correct file and folder name. If Dry-Run is OFF, it renames/moves the file. If Dry-Run is ON, it logs the intended change.
4.  **Save Cache**: Periodically (e.g., every 50 files) and upon completion, it saves the cataloged movie data to `library.json` to prevent data loss during long sessions.
5.  **Final Report**: After the loop, it presents a summary of actions and a clear report of any files that were skipped.
6.  **Confirmation Prompt**: If Dry-Run was ON, it will now ask: `Dry-run complete. Proceed with X renames and Y moves? (y/n)`. If the user confirms, the script re-runs the process with Dry-Run OFF.

**Integrated Edge Cases & Fail-Safes**:

  * **Unparseable Filenames**: If the regex fails, the file path is added to `unparseable_files` and the file is skipped.
  * **TMDB Matching Failures**: If TMDB returns no results or the results are too ambiguous, the file path is added to `unmatched_files` and the file is skipped.
  * **Duplicate Movie Files**: If a file is identified as a movie that's already in the catalog, its path is added to `duplicate_files` and it's skipped.
  * **API/File System Errors**: All network requests and file operations are wrapped in `try...except` blocks. A network failure will be retried once before skipping the file. A file permission error will cause the file to be skipped and reported.
  * **Interrupted Sessions**: The `library.json` cache is saved periodically to ensure progress isn't lost on large libraries.

-----

### **Option `[2]`: Fetch Trailers for Existing Movies**

**Goal**: To efficiently download missing trailers for the movies you already own.

**Flow**:

1.  **Pre-flight Check**: The script first verifies that `library.json` exists. It then performs a quick scan of `/Movies` to find any video files that are *not* in the cache (unsanitized files).
2.  **Process**: It iterates through the clean movie list from `library.json`, checks if a trailer exists for each, and adds any missing trailers to a download queue.
3.  **Simulate/Execute**: The script begins the download process. If Dry-Run is OFF, it downloads the files. If ON, it logs the trailers it intends to download.
4.  **Final Report**: It provides a summary of downloads and displays a clear warning if any unsanitized files were detected during the pre-flight check, prompting the user to run option `[1]`.
5.  **Confirmation Prompt**: If Dry-Run was ON, it will ask: `Dry-run complete. Proceed with downloading X trailers? (y/n)`.

-----

### **Option `[3]`: Fetch Upcoming Movie Trailers**

**Goal**: To discover new trailers and set them up with placeholders for your cinema experience.

**Flow**:

1.  **Query TMDB**: Fetches a list of new/popular movies.
2.  **Smart Caching**: It uses `upcoming_cache.json` to avoid redundant API calls, refreshing the data if it's more than 24 hours old.
3.  **Filter**: It checks against `known_failures.json` to skip trailers that are known to be unavailable.
4.  **Simulate/Execute**: It downloads the trailer into the `/Trailers` folder and generates the black `backdrop.jpg` and the 1-second video placeholder. If Dry-Run is ON, it logs these intended actions.
5.  **Confirmation Prompt**: If Dry-Run was ON, it will ask: `Dry-run complete. Proceed with downloading X trailers and creating assets? (y/n)`.

-----

### **Option `[4]`: Sync Trailers with Movie Library**

**Goal**: To consolidate your media by moving trailers from `/Trailers` to `/Movies` once you acquire the full movie.

**Flow**:

1.  **Compare Libraries**: The script compares the folder names in `/Trailers` with the cataloged movie names in `library.json`.
2.  **Queue Actions**: For every match found, it queues a "move" action for the trailer and its assets, and a "delete" action for the now-empty folder in `/Trailers`.
3.  **Simulate/Execute**: It performs the queued file operations. If Dry-Run is ON, it logs the intended moves and deletions.
4.  **Confirmation Prompt**: If Dry-Run was ON, it will ask: `Dry-run complete. Proceed with syncing X trailers? (y/n)`.

-----

### **Option `[5]`: Library Status**

A read-only function that uses `library.json` to provide a dashboard of your collection:
      * Total number of movies.
      * A list of all movies that are missing a local trailer.
      * Breakdown of movies by decade or genre.

-----

### **Option `[6]`: Settings and Uitilities**

User may change settings that were generated in `config.json` upon first run. Settings may include (but not limited to):

- TMDB API
- Trailer fetching logic options
- Max threads to use
- trailer directory
- movie directory
- cache directory
- other settings that may need to be changed

User may also choose to clear ALL or selected caches.

-----

### Functionality Improvement

  * **Improved Trailer Finding Logic**: The trailer fetching mechanism is enhanced to prioritize trailers in a specific order: Official Trailer \> Unofficial Trailer \> Official Teaser, ensuring the best quality result.
  * **Comprehensive Caching System**:
      * **`library.json`**: The master inventory of your existing movie collection.
      * **`upcoming_cache.json`**: A timed cache to keep discovered movie lists fresh without spamming the API.
      * **`known_failures.json`**: A persistent list of movies without trailers to prevent repeated failed download attempts.