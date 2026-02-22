@echo off
echo Organizing CIU Agent project structure...
echo.

cd /d D:\projects\ciu_agent

:: Create folder structure
mkdir docs 2>nul
mkdir skills\git 2>nul
mkdir .claude 2>nul
mkdir ciu_agent\core 2>nul
mkdir ciu_agent\platform 2>nul
mkdir ciu_agent\models 2>nul
mkdir ciu_agent\config 2>nul
mkdir tests 2>nul
mkdir sessions 2>nul

:: Move docs
move /Y agents.md docs\agents.md
move /Y conductor.md docs\conductor.md
move /Y teams.md docs\teams.md
move /Y phases.md docs\phases.md
move /Y features.md docs\features.md
move /Y skills.md docs\skills.md
move /Y s001_ciu_agent_architecture.md docs\architecture.md

:: Move skills
move /Y SKILL.md skills\git\SKILL.md

:: These stay at root (no move needed)
:: CLAUDE.md
:: README.md

echo.
echo Done. Final structure:
echo.
tree /F /A

pause
