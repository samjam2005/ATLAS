# Playwright Fallback

This folder contains the original Playwright automation code for the TerpAI integration. 

We migrated to a direct REST API via `httpx` because the DOM-based Playwright approach was brittle, required maintaining user data directories, and forced us to use complex Windows async event-loop hacks (`ProactorEventLoop` wrappers) that were causing application startup issues.

However, if the NebulOne internal API is ever fully locked down, you can revert to using this code.

## Contents

- `terpai.py`: The original `TerpAIBridge` class that automates the TerpAI UI via an invisible browser.
- `refresh_session.py`: The standalone script used to refresh TerpAI headless cookies by launching an interactive Chrome window.
- `test_terpai.py`: The basic unit test script for the Playwright bridge.

## How to restore

If you need to use this instead of the API approach:
1. Copy `terpai.py` from here over the API version at `backend/services/terpai.py`.
2. Add `playwright` back to your `requirements.txt` and install it.
3. Bring back the `ProactorEventLoop` async wrapper in `run.py` to prevent Windows from freezing when the browser launches.
4. Copy `refresh_session.py` to the root `backend` folder and run it to log in.
