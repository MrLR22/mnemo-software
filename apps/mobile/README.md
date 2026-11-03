# Mobile app

**Now:** the web app is the mobile app. Open `http://<laptop IP>:8000` in the phone's browser (same Wi-Fi as the
laptop running the backend). "Record / choose video" opens the phone camera; wear the phone on the chest, record,
and the clip is uploaded to the backend. Nothing to install.

**Later:** a native Android app (camera stream in 4-s clips, background upload, notifications for alerts). It will
use exactly the same backend API (`services/api/app.py`), so nothing else changes.
