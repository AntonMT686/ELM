@echo off
rem Stops the ADA-ELM windows started by start-all.bat. Does not stop MySQL, OnlyOffice or GitLab.
taskkill /fi "WINDOWTITLE eq ADA-ELM backend*" /t /f >/dev/null 2>&1
taskkill /fi "WINDOWTITLE eq ADA-ELM worker*" /t /f >/dev/null 2>&1
taskkill /fi "WINDOWTITLE eq ADA-ELM frontend*" /t /f >/dev/null 2>&1
echo ADA-ELM stopped.
