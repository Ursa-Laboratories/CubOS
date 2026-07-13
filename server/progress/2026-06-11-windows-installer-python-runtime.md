# Windows Installer Python Runtime Repair

- Added a checked `Install-Python.ps1` step that installs the private app-local
  Python runtime and verifies `Python\python.exe` exists.
- Retained the bundled Python installer under the installed app directory so
  `Start Zoo` can repair a missing private runtime.
- Updated the launcher to reinstall runtime packages when it has to recreate
  the private Python runtime.
