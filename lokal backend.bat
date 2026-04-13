@echo off
echo 🔥 RUNNING...

echo.
echo 📦 BACKEND START...
cd backend
call uvicorn main:app --reload