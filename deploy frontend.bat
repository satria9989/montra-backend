@echo off
echo 🔥 RUNNING...

echo.
echo 📦 FRONTEND START...
cd frontend
call git add . && git commit -m "update" && git push

echo.
echo #Finish Deploy bro!
pause