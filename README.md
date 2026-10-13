# clip-provider

First import candidate for the Windows Hair Tutorial Collector. Registration is
`pending_onboarding`; this candidate is not approved for publication or production.
The original source folder remains untouched. Public provenance contains only
relative paths, byte sizes and hashes in `onboarding/CANDIDATE_MANIFEST.json`;
internal onboarding/audit records are retained outside this public candidate.

## Local setup

Use a separate checkout on Windows with Python including Tkinter. The included
song cutter uses Python 3.10+ syntax; offline checks used Python 3.12.14. Full runtime
and package-install compatibility still require verification. Dependencies
are observed source versions; no transitive lock or installation validation exists.
FFmpeg and FFprobe must be separately available on PATH. Their binary distribution
and license obligations were not reviewed and binaries are not included.

The browser-based search/Lens/fallback flows require installed Google Chrome at
`C:\Program Files\Google\Chrome\Application\chrome.exe` or
`C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`, the fixed locations
checked by the application. Installing the Python Playwright package alone does
not satisfy this prerequisite. Chrome was not installed or launched for onboarding.

`Song/auto_cut_reels.py` is included to support the existing **Cut songs** command.
It uses only Python's standard library plus FFmpeg/FFprobe on PATH. Music assets and
generated MP3/CSV output are excluded. The GUI passes an explicitly selected input;
standalone invocation without an input would scan its current working directory.
No real song was read or processed during import.

After dependency-install approval and package review, the intended setup is:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app\app.py
```

The app stores runtime data alongside this README, using its own file location.
Activate the virtual environment before using either launcher so `python` and
`pythonw.exe` resolve to the intended runtime. The launchers were not executed.
The imported Thai manual and historical README retain original-folder references;
use this README's setup paths for the imported checkout.

Do not copy browser profiles, credentials, queues, history or downloaded media
from the original folder. The optional StockOS connector retains a production API
default but has no configuration or key in this checkout. Do not configure it or
perform uploads, scheduling, logins, downloads or other external actions as part
of onboarding. Real operation requires separate authorization and source rights.

## Offline import checks

```powershell
python -I tests\import_checks.py
```

These checks compile source and the song helper without importing the application,
exercise selected pure functions with synthetic values, and check imported paths,
helper availability and credential/media/profile ignore rules using Git only.
They do not certify GUI behavior, media processing, dependencies or the connector.
See `onboarding/VALIDATION.json` for the actual run, remaining gates and evidence.

## Rights and publication

No source license or verified ownership statement was found. No license is granted
by this import. The requested GitHub repository is public; Owner must confirm the
right to publish the included code/docs and accept the public disclosure scope.
Downloaded tutorial assets and vendored third-party code/binaries are excluded.
The source also discloses production StockOS host/API route names, BUUBLE branding
and the manual's posting practices. These are existing source content, not keys.
Changing them to placeholders would change existing integration behavior; Owner
must explicitly accept this disclosure scope before public publication. Existing
runtime security/correctness findings remain unresolved and activation is not approved.
