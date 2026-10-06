@echo off
echo ========================================
echo  DATABASE CLEANUP SCRIPT
echo ========================================
echo.
echo WARNING: This will DELETE ALL DATA from the database!
echo.
echo This includes:
echo   - All users and profiles
echo   - All generated SOPs
echo   - All watchlist items
echo   - All scraped documents
echo   - All notifications
echo.
echo ========================================
pause
echo.
echo Running database reset...
python reset_db.py
echo.
echo ========================================
echo Database cleanup complete!
echo.
echo Next steps:
echo   1. Restart the backend server (run restart_server.bat)
echo   2. Register a new user from your mobile app
echo ========================================
pause
