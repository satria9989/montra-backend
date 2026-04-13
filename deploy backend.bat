@echo off
echo 🔥 RUNNING...

echo.
echo 📦 BACKEND START...
cd backend
call git add . && git commit -m "update" && git push

echo.
echo #Finish Deploy bro!
pause